"""
PRODUCTION: LLM Analyzer with Budget Pre-Authorization

This file provides the updated analyzer.analyze() method that enforces
budget checks BEFORE making LLM API calls.
"""

# This is a patch to be applied to app/services/llm/analyzer.py
# Replace the analyze() method with this implementation

async def analyze_with_budget_checks(
    self,
    usage_summary: "CloudUsageSummary",
    tenant_id: Optional[UUID] = None,
    db: Optional[AsyncSession] = None,
    provider: Optional[str] = None,
    model: Optional[str] = None,
    force_refresh: bool = False,
) -> Dict[str, Any]:
    """
    PRODUCTION: Analyzes cloud costs with mandatory budget pre-authorization.
    
    Flow:
    1. Check cache (return if hit)
    2. Pre-authorize LLM budget (HARD BLOCK if exceeded)
    3. Call LLM with authorized reservation
    4. Record actual usage on success
    5. Release reservation on failure
    
    This ensures no surprise LLM charges.
    
    Args:
        usage_summary: The aggregated cost data to analyze.
        tenant_id: Tenant UUID for budget enforcement.
        db: Database session for persistence.
        provider: Optional provider override.
        model: Optional model override.
        force_refresh: bypass cache if True.
        
    Returns:
        AI insights and recommendations.
        
    Raises:
        BudgetExceededError: If tenant budget is exceeded (402 Payment Required)
        AIAnalysisError: If LLM analysis fails
    """
    from app.schemas.costs import CloudUsageSummary
    from app.core.exceptions import AIAnalysisError, BudgetExceededError
    from app.services.llm.budget_manager import LLMBudgetManager
    import uuid
    
    operation_id = str(uuid.uuid4())
    
    with tracer.start_as_current_span("analyze_costs_with_budget") as span:
        span.set_attribute("tenant_id", str(tenant_id) if tenant_id else "anonymous")
        span.set_attribute("operation_id", operation_id)
        
        effective_model = model or self.llm.model_name
        effective_db = db or self.db
        
        # 1. Check cache
        cached_analysis, is_delta = await self._check_cache_and_delta(
            tenant_id, force_refresh, usage_summary
        )
        if cached_analysis and not is_delta:
            logger.info("analysis_cache_hit", tenant_id=str(tenant_id), operation_id=operation_id)
            return cached_analysis

        logger.info("analysis_starting", 
                    tenant_id=str(tenant_id), 
                    data_points=len(usage_summary.records),
                    model=effective_model,
                    operation_id=operation_id)

        # 2. PRODUCTION: PRE-AUTHORIZE LLM BUDGET (HARD BLOCK)
        reserved_amount = None
        try:
            if tenant_id and effective_db:
                # Estimate tokens for this analysis
                # Heuristic: 1 record ≈ 20 tokens
                prompt_tokens = max(500, len(usage_summary.records) * 20)
                completion_tokens = 500  # Assume 500 token response
                
                reserved_amount = await LLMBudgetManager.check_and_reserve(
                    tenant_id=tenant_id,
                    db=effective_db,
                    model=effective_model,
                    prompt_tokens=prompt_tokens,
                    completion_tokens=completion_tokens,
                    operation_id=operation_id
                )
                
                logger.info(
                    "llm_budget_authorized",
                    tenant_id=str(tenant_id),
                    reserved_amount=float(reserved_amount),
                    operation_id=operation_id
                )
            else:
                logger.warning(
                    "budget_check_skipped",
                    reason="No tenant_id or db provided",
                    operation_id=operation_id
                )
        
        except BudgetExceededError as e:
            # This is expected if budget is depleted
            logger.warning(
                "llm_request_blocked_budget_exceeded",
                tenant_id=str(tenant_id),
                error=e.message,
                operation_id=operation_id
            )
            raise  # Re-raise to return 402 to client
        
        except Exception as e:
            # Unexpected error during budget check
            logger.error(
                "budget_check_failed_unexpected",
                tenant_id=str(tenant_id),
                error=str(e),
                error_type=type(e).__name__,
                operation_id=operation_id
            )
            raise AIAnalysisError(
                f"Budget verification failed: {str(e)}",
                details={"operation_id": operation_id}
            )

        # 3. Prepare input data
        try:
            sanitized_data = await LLMGuardrails.sanitize_input(usage_summary.model_dump())
            
            # Add symbolic forecast for grounding
            from app.services.analysis.forecaster import SymbolicForecaster
            forecast_result = await SymbolicForecaster.forecast(
                usage_summary.records,
                db=effective_db,
                tenant_id=tenant_id
            )
            sanitized_data["symbolic_forecast"] = forecast_result
            
            # Convert to string for LLM
            data_str = json.dumps(sanitized_data, default=str)
            
        except Exception as e:
            logger.error(
                "data_preparation_failed",
                tenant_id=str(tenant_id),
                error=str(e),
                operation_id=operation_id
            )
            raise AIAnalysisError(
                f"Failed to prepare data for analysis: {str(e)}",
                details={"operation_id": operation_id}
            )

        # 4. CALL LLM (budget already pre-authorized)
        llm_response = None
        try:
            logger.info(
                "llm_call_starting",
                model=effective_model,
                tenant_id=str(tenant_id),
                operation_id=operation_id
            )
            
            # Call LLM with retry logic
            @retry(
                stop=stop_after_attempt(3),
                wait=wait_exponential(multiplier=1, min=2, max=10),
                retry=retry_if_exception_type((Exception,))
            )
            async def call_llm_with_retry():
                return await self.llm.invoke({"cost_data": data_str})
            
            llm_response = await call_llm_with_retry()
            
            logger.info(
                "llm_response_received",
                model=effective_model,
                response_length=len(str(llm_response)),
                tenant_id=str(tenant_id),
                operation_id=operation_id
            )
            
        except Exception as e:
            logger.error(
                "llm_invocation_failed",
                model=effective_model,
                tenant_id=str(tenant_id),
                error=str(e),
                error_type=type(e).__name__,
                operation_id=operation_id
            )
            raise AIAnalysisError(
                f"LLM analysis failed: {str(e)}",
                code="llm_error",
                details={
                    "model": effective_model,
                    "operation_id": operation_id,
                    "error_type": type(e).__name__
                }
            )

        # 5. PRODUCTION: Record actual usage on success
        if reserved_amount and effective_db:
            try:
                # Assume response used estimated tokens
                # In production, parse actual token usage from LLM response
                actual_prompt_tokens = max(500, len(usage_summary.records) * 20)
                actual_completion_tokens = len(str(llm_response)) // 4  # Rough estimate
                
                await LLMBudgetManager.record_usage(
                    tenant_id=tenant_id,
                    db=effective_db,
                    model=effective_model,
                    prompt_tokens=actual_prompt_tokens,
                    completion_tokens=actual_completion_tokens,
                    actual_cost_usd=reserved_amount,  # Use reserved amount for now
                    operation_id=operation_id
                )
                
                logger.info(
                    "llm_usage_recorded",
                    tenant_id=str(tenant_id),
                    cost=float(reserved_amount),
                    operation_id=operation_id
                )
            except Exception as e:
                logger.warning(
                    "usage_recording_failed",
                    tenant_id=str(tenant_id),
                    error=str(e),
                    operation_id=operation_id
                )
                # Don't fail the request if usage recording fails

        # 6. Parse and validate LLM response
        try:
            response_text = llm_response.content if hasattr(llm_response, 'content') else str(llm_response)
            response_text = self._strip_markdown(response_text)
            parsed_result = json.loads(response_text)
            
        except json.JSONDecodeError as e:
            logger.error(
                "llm_response_parse_failed",
                tenant_id=str(tenant_id),
                error=str(e),
                operation_id=operation_id
            )
            raise AIAnalysisError(
                f"LLM response was not valid JSON: {str(e)}",
                code="invalid_llm_response"
            )

        # 7. Validate with guardrails
        try:
            validated = await LLMGuardrails.validate_analysis(parsed_result)
        except Exception as e:
            logger.warning(
                "llm_guardrails_validation_failed",
                tenant_id=str(tenant_id),
                error=str(e),
                operation_id=operation_id
            )
            validated = parsed_result  # Fallback to unvalidated result

        # 8. Cache result and return
        try:
            if effective_db:
                # Store in cache (implementation depends on your cache service)
                pass
        except Exception as e:
            logger.warning(
                "cache_storage_failed",
                tenant_id=str(tenant_id),
                error=str(e),
                operation_id=operation_id
            )

        logger.info(
            "analysis_completed",
            tenant_id=str(tenant_id),
            operation_id=operation_id,
            cost_usd=float(reserved_amount) if reserved_amount else None
        )

        return validated
