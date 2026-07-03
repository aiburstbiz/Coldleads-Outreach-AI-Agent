from unittest.mock import patch, MagicMock
from dev2_delivery.gmail_sender import send_email


def test_send_email_success():
    mock_service = MagicMock()
    mock_service.users().messages().send().execute.return_value = {
        "id": "msg_abc123"
    }

    with patch("dev2_delivery.gmail_sender.get_gmail_service", return_value=mock_service):
        result = send_email(
            to="test@example.com",
            subject="Test Subject",
            body_html="<p>Hello</p>",
        )

    assert result["success"] is True
    assert result["message_id"] == "msg_abc123"


def test_send_email_failure():
    from googleapiclient.errors import HttpError
    from unittest.mock import Mock
    import json

    mock_service = MagicMock()
    mock_resp = Mock()
    mock_resp.status = 403
    mock_resp.reason = "Forbidden"
    mock_service.users().messages().send().execute.side_effect = HttpError(
        resp=mock_resp, content=b'{"error": "forbidden"}'
    )

    with patch("dev2_delivery.gmail_sender.get_gmail_service", return_value=mock_service):
        result = send_email(
            to="test@example.com",
            subject="Test",
            body_html="<p>Hi</p>",
        )

    assert result["success"] is False
    assert "error" in result