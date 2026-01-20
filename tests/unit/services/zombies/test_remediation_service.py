import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4
from decimal import Decimal
from datetime import datetime, timezone
from botocore.exceptions import ClientError
from sqlalchemy.ext.asyncio import AsyncSession
from app.services.zombies.remediation_service import RemediationService
from app.models.remediation import RemediationRequest, RemediationStatus, RemediationAction
from app.models.aws_connection import AWSConnection

@pytest.fixture
def db_session():
    session = AsyncMock(spec=AsyncSession)
    # Mock db.execute().scalar_one_or_none() for auth checks
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = MagicMock()
    session.execute.return_value = mock_result
    return session

@pytest.fixture
def remediation_service(db_session):
    return RemediationService(db_session)

@pytest.mark.asyncio
async def test_create_request_success(remediation_service, db_session):
    # Setup
    tenant_id = uuid4()
    user_id = uuid4()
    connection_id = uuid4()
    
    # Execute
    request = await remediation_service.create_request(
        tenant_id=tenant_id,
        user_id=user_id,
        resource_id="vol-123",
        resource_type="ebs_volume",
        provider="aws",
        connection_id=connection_id,
        action=RemediationAction.DELETE_VOLUME,
        estimated_savings=50.0,
        create_backup=True
    )
    
    # Assert
    assert request.resource_id == "vol-123"
    assert request.status == RemediationStatus.PENDING
    assert request.create_backup is True
    db_session.add.assert_called_once()
    db_session.commit.assert_called_once()

@pytest.mark.asyncio
async def test_process_remediation_aws_delete_volume_success(remediation_service, db_session):
    # Setup
    req = RemediationRequest(
        id=uuid4(),
        resource_id="vol-123",
        resource_type="ebs_volume",
        provider="aws",
        action=RemediationAction.DELETE_VOLUME,
        status=RemediationStatus.APPROVED
    )
    conn = AWSConnection(id=uuid4(), role_arn="arn:aws:iam::123:role/test")
    
    mock_client = AsyncMock()
    mock_client.delete_volume.return_value = {"ResponseMetadata": {"HTTPStatusCode": 200}}
    
    # aioboto3 returns an async context manager
    mock_cm = MagicMock()
    mock_cm.__aenter__.return_value = mock_client
    
    with patch.object(remediation_service, "_get_client", return_value=mock_cm):
        # Execute
        result = await remediation_service.process_remediation(req, conn)
        
        # Assert
        assert result is True
        assert req.status == RemediationStatus.COMPLETED
        mock_client.delete_volume.assert_called_once_with(VolumeId="vol-123")

@pytest.mark.asyncio
async def test_process_remediation_aws_access_denied(remediation_service, db_session):
    # Setup
    req = RemediationRequest(
        id=uuid4(),
        resource_id="vol-123",
        resource_type="ebs_volume",
        provider="aws",
        action=RemediationAction.DELETE_VOLUME,
        status=RemediationStatus.APPROVED
    )
    conn = AWSConnection(id=uuid4())
    
    # botocore exceptions are NOT async
    mock_client = AsyncMock()
    mock_client.delete_volume.side_effect = ClientError(
        {"Error": {"Code": "AccessDenied", "Message": "Permission Denied"}}, "DeleteVolume"
    )
    
    mock_cm = MagicMock()
    mock_cm.__aenter__.return_value = mock_client
    
    with patch.object(remediation_service, "_get_client", return_value=mock_cm):
        # Execute
        result = await remediation_service.process_remediation(req, conn)
        
        # Assert
        assert result is False
        assert req.status == RemediationStatus.FAILED
        assert "AccessDenied" in req.execution_error

@pytest.mark.asyncio
async def test_approve_request(remediation_service, db_session):
    # Setup
    request_id = uuid4()
    tenant_id = uuid4()
    reviewer_id = uuid4()
    req = RemediationRequest(id=request_id, tenant_id=tenant_id, status=RemediationStatus.PENDING)
    
    mock_res = MagicMock()
    mock_res.scalar_one_or_none.return_value = req
    db_session.execute.return_value = mock_res
    
    # Execute
    updated_req = await remediation_service.approve(request_id, tenant_id, reviewer_id)
    
    # Assert
    assert updated_req.status == RemediationStatus.APPROVED
    assert updated_req.reviewed_by_user_id == reviewer_id
    db_session.commit.assert_called_once()
