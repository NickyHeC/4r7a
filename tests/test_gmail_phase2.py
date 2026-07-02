"""Unit tests for Phase-2 Gmail heuristics."""

from company_brain.agents.operations.shared.complexity import is_simple_reply
from company_brain.agents.operations.shared.decision import classify_sent_message


def _thread(messages: list[dict]) -> dict:
    return {"messages": messages}


def _msg(subject: str = "", body: str = "", from_: str = "them@co.com") -> dict:
    import base64

    data = base64.urlsafe_b64encode(body.encode()).decode().rstrip("=")
    return {
        "payload": {
            "headers": [
                {"name": "Subject", "value": subject},
                {"name": "From", "value": from_},
            ],
            "mimeType": "text/plain",
            "body": {"data": data},
        },
        "snippet": body[:100],
    }


def test_decision_ack():
    assert classify_sent_message(_msg(body="Thanks!")) == "ack"
    assert classify_sent_message(_msg(body="Got it, pass.")) == "ack"


def test_decision_real():
    body = "We decided to move forward with the Series A terms as discussed."
    assert classify_sent_message(_msg(body=body)) == "decision"


def test_simple_reply_thread():
    thread = _thread([_msg(subject="Quick question", body="Are you free Tuesday?")])
    assert is_simple_reply(thread) is True


def test_complex_reply_thread():
    thread = _thread(
        [
            _msg(subject="MSA review", body="Please review the contract terms?"),
            _msg(subject="Re: MSA", body="Also legal needs your signature."),
        ]
    )
    assert is_simple_reply(thread) is False
