"""
Symbolic Forecasting Engine

Provides deterministic, mathematical cost forecasts using statistical models (statsmodels)
to provide a reliable baseline for the AI interpretation layer.
"""

from decimal import Decimal
from typing import List, Dict, Any, Optional
import pandas as pd
import numpy as np
from statsmodels.tsa.holtwinters import ExponentialSmoothing
try:
    from prophet import Prophet
    PROPHET_AVAILABLE = True
except ImportError:
    PROPHET_AVAILABLE = False

from app.schemas.costs import CostRecord
from app.models.anomaly_marker import AnomalyMarker
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from uuid import UUID
import structlog

logger = structlog.get_logger()

class SymbolicForecaster:
    """
    Deterministic forecasting engine for cloud costs.
    Uses Neuro-Symbolic bridge to provide AI with mathematical grounding.
    """

    @staticmethod
    def _detect_outliers(df: pd.DataFrame) -> pd.DataFrame:
        """
        Uses Median Absolute Deviation (MAD) to detect outliers in the cost data.
        More robust than Z-score for sudden billing spikes.
        """
        median = df['y'].median()
        mad = (df['y'] - median).abs().median()
        if mad == 0:
            return df.assign(is_outlier=False)
        
        # Threshold of 3.5 is standard for MAD-based outlier detection
        df['z_score_mad'] = 0.6745 * (df['y'] - median) / mad
        df['is_outlier'] = df['z_score_mad'].abs() > 3.5
        return df

    @classmethod
    async def forecast(
        cls, 
        history: List[CostRecord], 
        days: int = 30, 
        service_filter: Optional[str] = None,
        db: Optional[AsyncSession] = None,
        tenant_id: Optional[UUID] = None,
        confidence_interval_width: float = 0.95
    ) -> Dict[str, Any]:
        """
        Generates a multi-day forecast based on historical cost records.
        Prioritizes Facebook Prophet for seasonality/trend detection.
        Now includes Anomaly Detection, Confidence Intervals, and User Markers.
        """
        if service_filter:
            history = [r for r in history if r.service == service_filter]

        if len(history) < 7:
            logger.warning("insufficient_data_for_symbolic_forecast", count=len(history))
            return {"forecast": [], "confidence": "low", "reason": f"Need at least 7 days of data, got {len(history)}"}

        # 1. Prepare Data
        df = pd.DataFrame([
            {"ds": r.date, "y": float(r.amount)} 
            for r in history
        ])
        df['ds'] = pd.to_datetime(df['ds'])
        
        # Ensure daily continuity (fill missing days with mean, handle zero division)
        df = df.sort_values('ds').set_index('ds').resample('D').mean().fillna(0).reset_index()

        # 1.5 Fetch and apply Anomaly Markers (FinOps Phase 3.2)
        holidays_df = None
        markers_applied = 0
        if db and tenant_id:
            try:
                stmt = select(AnomalyMarker).where(AnomalyMarker.tenant_id == tenant_id)
                if service_filter:
                    stmt = stmt.where(
                        (AnomalyMarker.service_filter == service_filter) | 
                        (AnomalyMarker.service_filter == None)
                    )
                result = await db.execute(stmt)
                markers = result.scalars().all()
                
                if markers:
                    holidays_list = []
                    for m in markers:
                        # Add a row for each day in the marker range
                        marker_days = pd.date_range(start=m.start_date, end=m.end_date)
                        for d in marker_days:
                            holidays_list.append({
                                'ds': d,
                                'holiday': m.marker_type,
                                'lower_window': 0,
                                'upper_window': 0
                            })
                        if m.exclude_from_training:
                            # Robustly mask out training data for marked anomalies
                            mask = (df['ds'].dt.date >= m.start_date) & (df['ds'].dt.date <= m.end_date)
                            df.loc[mask, 'y'] = np.nan
                    
                    df['y'] = df['y'].interpolate(method='linear').fillna(0)
                    holidays_df = pd.DataFrame(holidays_list)
                    markers_applied = len(markers)
                    logger.info("applied_anomaly_markers", count=markers_applied)
            except Exception as e:
                logger.warning("failed_to_fetch_anomaly_markers", error=str(e))

        # 2. Forensic Anomaly Detection (FinOps Phase 3)
        df = cls._detect_outliers(df)
        anomalies = df[df['is_outlier']].copy()
        
        # 3. Accuracy Tracking (Backtesting MAPE)
        mape = None
        if len(df) >= 14:
            # Simple backtest: project the last 7 days and compare to actuals
            train_df = df.iloc[:-7]
            test_df = df.iloc[-7:]
            if PROPHET_AVAILABLE:
                try:
                    m_bt = Prophet(weekly_seasonality=True, interval_width=confidence_interval_width).fit(train_df)
                    bt_forecast = m_bt.predict(m_bt.make_future_dataframe(periods=7))
                    bt_yhat = bt_forecast.tail(7)['yhat'].values
                    bt_actual = test_df['y'].values
                    # Weighted MAPE to avoid division by zero
                    denom = np.abs(bt_actual).sum()
                    if denom > 0:
                        mape = (np.abs(bt_actual - bt_yhat).sum() / denom) * 100
                except Exception:
                    pass

        # 4. Main Forecasting (Prophet)
        if PROPHET_AVAILABLE and len(df) >= 14:
            try:
                m = Prophet(
                    yearly_seasonality=False,
                    weekly_seasonality=True,
                    daily_seasonality=False,
                    changepoint_prior_scale=0.05,
                    interval_width=confidence_interval_width,
                    holidays=holidays_df
                )
                m.fit(df)
                
                future = m.make_future_dataframe(periods=days)
                forecast = m.predict(future)
                
                future_df = forecast.tail(days)
                
                forecast_results = []
                for _, row in future_df.iterrows():
                    forecast_results.append({
                        "date": row['ds'].date().isoformat(),
                        "amount": Decimal(str(max(0, round(row['yhat'], 4)))),
                        "confidence_lower": Decimal(str(max(0, round(row['yhat_lower'], 4)))),
                        "confidence_upper": Decimal(str(max(0, round(row['yhat_upper'], 4)))),
                        "volatility": round(float(row['yhat_upper'] - row['yhat_lower']), 4)
                    })

                return {
                    "forecast": forecast_results,
                    "total_forecasted_cost": Decimal(str(round(future_df['yhat'].sum(), 2))),
                    "confidence": "high" if mape and mape < 10 else "medium",
                    "accuracy_mape": round(float(mape), 2) if mape is not None else None,
                    "model": "Prophet",
                    "diagnostics": {
                        "anomalies_detected": len(anomalies),
                        "anomaly_dates": [d.date().isoformat() for d in anomalies['ds']],
                        "service_filter": service_filter,
                        "markers_applied": markers_applied,
                        "interval_width": confidence_interval_width
                    }
                }
            except Exception as e:
                logger.error("prophet_forecast_failed_falling_back", error=str(e))

        # 5. Fallback: Holt-Winters (Statsmodels)
        try:
            ts = df.set_index('ds')['y']
            if ts.sum() == 0:
                # Handle all-zero costs gracefully
                forecast_results = []
                for i in range(days):
                    forecast_results.append({
                        "date": (df['ds'].iloc[-1] + pd.Timedelta(days=i+1)).date().isoformat(),
                        "amount": Decimal("0.0"),
                        "confidence_lower": Decimal("0.0"),
                        "confidence_upper": Decimal("0.0")
                    })
                return {
                    "forecast": forecast_results,
                    "total_forecasted_cost": Decimal("0.0"),
                    "confidence": "medium",
                    "model": "Zero-Cost Baseline",
                    "diagnostics": {"service_filter": service_filter}
                }

            try:
                model = ExponentialSmoothing(ts, seasonal_periods=7, trend='add', seasonal='add').fit()
                model_name = "Holt-Winters (Triple)"
            except Exception:
                model = ExponentialSmoothing(ts, trend='add', seasonal=None).fit()
                model_name = "Holt-Winters (Double)"

            forecast_values = model.forecast(days)
            
            # Statistically sound confidence bands for Holt-Winters
            # HW residuals are used as a proxy for prediction interval
            residuals = ts - model.fittedvalues
            se = np.std(residuals)
            if se == 0: se = 0.01 # Avoid zero SE for static data
            
            forecast_results = []
            for i, val in enumerate(forecast_values):
                # Prediction interval for HW grows with sqrt of periods ahead
                # Z=1.96 for 95% confidence
                z_score = 1.96 if confidence_interval_width >= 0.95 else 1.645 # simple mapping
                interval = z_score * se * np.sqrt(i + 1)
                
                forecast_results.append({
                    "date": (df['ds'].iloc[-1] + pd.Timedelta(days=i+1)).date().isoformat(),
                    "amount": Decimal(str(max(0, round(val, 4)))),
                    "confidence_lower": Decimal(str(max(0, round(val - interval, 4)))),
                    "confidence_upper": Decimal(str(max(0, round(val + interval, 4))))
                })

            return {
                "forecast": forecast_results,
                "total_forecasted_cost": Decimal(str(round(sum(forecast_values), 2))),
                "confidence": "medium",
                "accuracy_mape": round(float(mape), 2) if mape is not None else None,
                "model": f"{model_name} (Fallback)",
                "diagnostics": {
                    "anomalies_detected": len(anomalies),
                    "service_filter": service_filter,
                    "interval_width": confidence_interval_width
                }
            }

        except Exception as e:
            logger.error("symbolic_forecast_failed_completely", error=str(e))
            return {"forecast": [], "confidence": "error", "error": str(e)}

        except Exception as e:
            logger.error("symbolic_forecast_failed_completely", error=str(e))
            return {"forecast": [], "confidence": "error", "error": str(e)}

    @classmethod
    async def forecast_carbon(
        cls, 
        history: List[CostRecord], 
        region: str = "us-east-1", 
        days: int = 30,
        service_filter: Optional[str] = None,
        db: Optional[AsyncSession] = None,
        tenant_id: Optional[UUID] = None
    ) -> Dict[str, Any]:
        """
        Generates a carbon emission forecast based on cost forecast.
        """
        cost_forecast_res = await cls.forecast(history, days, service_filter, db, tenant_id)
        if cost_forecast_res.get("confidence") == "error":
            return cost_forecast_res

        from app.services.carbon.calculator import (
            SERVICE_ENERGY_FACTORS, 
            AWS_PUE, 
            REGION_CARBON_INTENSITY, 
            EMBODIED_EMISSIONS_FACTOR
        )

        energy_factor = Decimal(str(SERVICE_ENERGY_FACTORS["default"]))
        pue = Decimal(str(AWS_PUE))
        intensity = Decimal(str(REGION_CARBON_INTENSITY.get(region, REGION_CARBON_INTENSITY["default"])))
        embodied_factor = Decimal(str(EMBODIED_EMISSIONS_FACTOR))

        carbon_forecast = []
        total_co2_kg = Decimal("0")

        for item in cost_forecast_res["forecast"]:
            cost = item["amount"]
            energy_kwh = cost * energy_factor * pue
            
            # Scope 2 (Operational) + Scope 3 (Embodied)
            scope2_kg = (energy_kwh * intensity) / Decimal("1000")
            scope3_kg = energy_kwh * embodied_factor
            
            daily_co2_kg = scope2_kg + scope3_kg
            total_co2_kg += daily_co2_kg

            carbon_forecast.append({
                "date": item["date"],
                "co2_kg": round(float(daily_co2_kg), 4)
            })

        return {
            "forecast": carbon_forecast,
            "total_forecasted_co2_kg": round(float(total_co2_kg), 2),
            "confidence": cost_forecast_res["confidence"],
            "model": cost_forecast_res["model"],
            "region": region,
            "unit": "kg CO2e"
        }
