import smtplib

from app import mail


class FakeSMTP:
    instances = []

    def __init__(self, host, port, timeout):
        self.host, self.port, self.sent, self.tls, self.login_as = host, port, [], False, None
        FakeSMTP.instances.append(self)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def starttls(self):
        self.tls = True

    def login(self, user, password):
        self.login_as = (user, password)

    def send_message(self, msg):
        self.sent.append(msg)


def test_send_email_builds_the_message_and_hands_it_to_the_smtp_server(monkeypatch):
    FakeSMTP.instances.clear()
    monkeypatch.setattr(smtplib, "SMTP", FakeSMTP)
    mail.send_email("ada@example.com", "Hello", "Body text")
    [smtp] = FakeSMTP.instances
    [msg] = smtp.sent
    assert (msg["To"], msg["Subject"], msg.get_content().strip()) == ("ada@example.com", "Hello", "Body text")
    assert smtp.login_as is None and not smtp.tls  # local Mailpit: no TLS, no login


def test_send_email_uses_tls_and_login_when_credentials_are_configured(monkeypatch):
    FakeSMTP.instances.clear()
    monkeypatch.setattr(smtplib, "SMTP", FakeSMTP)
    monkeypatch.setattr(mail, "SMTP_USER", "me@example.com")
    monkeypatch.setattr(mail, "SMTP_PASSWORD", "app-password")
    mail.send_email("ada@example.com", "Hello", "Body")
    [smtp] = FakeSMTP.instances
    assert smtp.tls and smtp.login_as == ("me@example.com", "app-password")


def test_a_dead_smtp_server_never_breaks_the_request(monkeypatch):
    def refuse(*args, **kwargs):
        raise ConnectionRefusedError("smtp down")

    monkeypatch.setattr(smtplib, "SMTP", refuse)
    mail.send_email("ada@example.com", "Hello", "Body")  # must not raise
