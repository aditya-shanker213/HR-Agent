"""
Email notification service.

Supports two email providers:
1. SMTP (for self-hosted or standard SMTP servers)
2. SendGrid (cloud email service)

The service automatically selects the provider based on configuration.
If both are configured, SendGrid takes priority.

Used for:
- OTP emails (signup, password reset)
- Leave status notifications
- Claim approval notifications
- HR escalation alerts
- Step-up auth notifications
"""

import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import List, Optional

from backend.app.core.config import settings


class EmailService:
    """
    Email service with support for SMTP and SendGrid.
    
    Pattern:
    - Check configuration at initialization
    - Select provider based on available settings
    - Provide a unified send_email() interface
    """

    def __init__(self):
        """
        Initialize email service.
        
        Determines which email provider to use based on configuration.
        """
        self.provider = self._detect_provider()
        
        if self.provider is None:
            print("⚠ Warning: No email provider configured. Emails will not be sent.")
        else:
            print(f"✓ Email service initialized with provider: {self.provider}")

    def _detect_provider(self) -> Optional[str]:
        """
        Detect which email provider is configured.
        
        Priority:
        1. SendGrid (if configured)
        2. SMTP (if configured)
        3. None (no provider)
        """
        if settings.has_sendgrid_config():
            return "sendgrid"
        elif settings.has_smtp_config():
            return "smtp"
        else:
            return None

    async def send_email(
        self,
        to_email: str,
        subject: str,
        body: str,
        from_email: Optional[str] = None,
        from_name: Optional[str] = None,
        html_body: Optional[str] = None,
        cc: Optional[List[str]] = None,
        bcc: Optional[List[str]] = None,
    ) -> bool:
        """
        Send email using configured provider.
        
        Args:
            to_email: Recipient email address
            subject: Email subject line
            body: Plain text email body
            from_email: Optional sender email (uses config default if not provided)
            from_name: Optional sender name (uses config default if not provided)
            html_body: Optional HTML email body (for rich formatting)
            cc: Optional list of CC recipients
            bcc: Optional list of BCC recipients
        
        Returns:
            True if email sent successfully, False otherwise
        """
        if self.provider is None:
            print(f"⚠ Email not sent (no provider): {to_email} - {subject}")
            return False

        try:
            if self.provider == "sendgrid":
                return await self._send_via_sendgrid(
                    to_email=to_email,
                    subject=subject,
                    body=body,
                    from_email=from_email,
                    from_name=from_name,
                    html_body=html_body,
                    cc=cc,
                    bcc=bcc,
                )
            elif self.provider == "smtp":
                return await self._send_via_smtp(
                    to_email=to_email,
                    subject=subject,
                    body=body,
                    from_email=from_email,
                    from_name=from_name,
                    html_body=html_body,
                    cc=cc,
                    bcc=bcc,
                )
            else:
                return False

        except Exception as e:
            print(f"✗ Failed to send email to {to_email}: {e}")
            return False

    async def _send_via_smtp(
        self,
        to_email: str,
        subject: str,
        body: str,
        from_email: Optional[str] = None,
        from_name: Optional[str] = None,
        html_body: Optional[str] = None,
        cc: Optional[List[str]] = None,
        bcc: Optional[List[str]] = None,
    ) -> bool:
        """
        Send email via SMTP.
        
        Supports both TLS (port 587) and SSL (port 465).
        """
        from_email = from_email or settings.SMTP_FROM_EMAIL
        from_name = from_name or settings.SMTP_FROM_NAME

        if not from_email:
            raise ValueError("SMTP_FROM_EMAIL is not configured")

        # Build sender address with name
        if from_name:
            sender = f"{from_name} <{from_email}>"
        else:
            sender = from_email

        # Create message
        message = MIMEMultipart("alternative")
        message["Subject"] = subject
        message["From"] = sender
        message["To"] = to_email

        if cc:
            message["Cc"] = ", ".join(cc)

        # Attach plain text body
        text_part = MIMEText(body, "plain", "utf-8")
        message.attach(text_part)

        # Attach HTML body if provided
        if html_body:
            html_part = MIMEText(html_body, "html", "utf-8")
            message.attach(html_part)

        # Build recipient list
        recipients = [to_email]
        if cc:
            recipients.extend(cc)
        if bcc:
            recipients.extend(bcc)

        # Send email
        try:
            if settings.SMTP_USE_SSL:
                # SSL connection (port 465)
                with smtplib.SMTP_SSL(
                    settings.SMTP_HOST,
                    settings.SMTP_PORT,
                    timeout=10,
                ) as server:
                    if settings.SMTP_USER and settings.SMTP_PASSWORD:
                        server.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
                    server.send_message(message, from_addr=from_email, to_addrs=recipients)

            else:
                # TLS connection (port 587)
                with smtplib.SMTP(
                    settings.SMTP_HOST,
                    settings.SMTP_PORT,
                    timeout=10,
                ) as server:
                    if settings.SMTP_USE_TLS:
                        server.starttls()

                    if settings.SMTP_USER and settings.SMTP_PASSWORD:
                        server.login(settings.SMTP_USER, settings.SMTP_PASSWORD)

                    server.send_message(message, from_addr=from_email, to_addrs=recipients)

            print(f"✓ Email sent via SMTP to {to_email}")
            return True

        except smtplib.SMTPAuthenticationError as e:
            print(f"✗ SMTP authentication failed: {e}")
            return False
        except smtplib.SMTPException as e:
            print(f"✗ SMTP error: {e}")
            return False
        except Exception as e:
            print(f"✗ Failed to send email via SMTP: {e}")
            return False

    async def _send_via_sendgrid(
        self,
        to_email: str,
        subject: str,
        body: str,
        from_email: Optional[str] = None,
        from_name: Optional[str] = None,
        html_body: Optional[str] = None,
        cc: Optional[List[str]] = None,
        bcc: Optional[List[str]] = None,
    ) -> bool:
        """
        Send email via SendGrid API.
        
        Requires sendgrid package:
        pip install sendgrid
        """
        try:
            from sendgrid import SendGridAPIClient
            from sendgrid.helpers.mail import Mail, Cc, Bcc
        except ImportError:
            print("✗ SendGrid package not installed. Run: pip install sendgrid")
            return False

        from_email = from_email or settings.SENDGRID_FROM_EMAIL
        from_name = from_name or settings.SMTP_FROM_NAME

        if not from_email:
            raise ValueError("SENDGRID_FROM_EMAIL is not configured")

        # Build sender tuple
        if from_name:
            sender = (from_email, from_name)
        else:
            sender = from_email

        # Create message
        message = Mail(
            from_email=sender,
            to_emails=to_email,
            subject=subject,
            plain_text_content=body,
            html_content=html_body,
        )

        # Add CC recipients
        if cc:
            for cc_email in cc:
                message.add_cc(Cc(cc_email))

        # Add BCC recipients
        if bcc:
            for bcc_email in bcc:
                message.add_bcc(Bcc(bcc_email))

        try:
            sg = SendGridAPIClient(settings.SENDGRID_API_KEY)
            response = sg.send(message)

            if response.status_code in [200, 201, 202]:
                print(f"✓ Email sent via SendGrid to {to_email}")
                return True
            else:
                print(f"✗ SendGrid returned status {response.status_code}")
                return False

        except Exception as e:
            print(f"✗ Failed to send email via SendGrid: {e}")
            return False

    def is_configured(self) -> bool:
        """Check if email service is configured."""
        return self.provider is not None

    def get_provider(self) -> Optional[str]:
        """Get current email provider name."""
        return self.provider


# -------------------------
# Singleton instance
# -------------------------

_email_service_instance: Optional[EmailService] = None


def get_email_service() -> EmailService:
    """
    Get singleton EmailService instance.
    
    Usage:
        from backend.app.notifications.email_service import get_email_service
        
        email_service = get_email_service()
        await email_service.send_email(...)
    """
    global _email_service_instance

    if _email_service_instance is None:
        _email_service_instance = EmailService()

    return _email_service_instance


# -------------------------
# Convenience functions
# -------------------------

async def send_otp_email(
    to_email: str,
    otp: str,
    purpose: str,
    expiry_minutes: int = 10,
) -> bool:
    """
    Send OTP email with standardized formatting.
    
    Args:
        to_email: Recipient email
        otp: 6-digit OTP code
        purpose: "signup" or "forgot_password"
        expiry_minutes: OTP expiry time
    
    Returns:
        True if sent successfully
    """
    email_service = get_email_service()

    if purpose == "signup":
        subject = "Verify your HR AI Agent account"
        body = f"""Hello,

Your signup verification code is: {otp}

This code will expire in {expiry_minutes} minutes.

If you did not request this code, please ignore this email.

Best regards,
HR AI Agent Team
"""
    elif purpose == "forgot_password":
        subject = "Reset your HR AI Agent password"
        body = f"""Hello,

Your password reset verification code is: {otp}

This code will expire in {expiry_minutes} minutes.

If you did not request this code, please ignore this email.

Best regards,
HR AI Agent Team
"""
    else:
        subject = "Your HR AI Agent verification code"
        body = f"""Hello,

Your verification code is: {otp}

This code will expire in {expiry_minutes} minutes.

If you did not request this code, please ignore this email.

Best regards,
HR AI Agent Team
"""

    return await email_service.send_email(
        to_email=to_email,
        subject=subject,
        body=body,
    )


async def send_welcome_email(to_email: str, username: str) -> bool:
    """
    Send welcome email after successful signup.
    
    Optional: Can be called after signup verification.
    """
    email_service = get_email_service()

    subject = "Welcome to HR AI Agent!"
    body = f"""Hello {username},

Welcome to HR AI Agent! Your account has been successfully created.

You can now login and access:
- Leave management
- Claim submissions
- Salary information
- HR policy queries

If you have any questions, please contact your HR team.

Best regards,
HR AI Agent Team
"""

    return await email_service.send_email(
        to_email=to_email,
        subject=subject,
        body=body,
    )


async def send_password_reset_confirmation(to_email: str) -> bool:
    """
    Send confirmation email after password reset.
    """
    email_service = get_email_service()

    subject = "Your HR AI Agent password has been reset"
    body = """Hello,

Your password has been successfully reset.

If you did not make this change, please contact your HR team immediately.

Best regards,
HR AI Agent Team
"""

    return await email_service.send_email(
        to_email=to_email,
        subject=subject,
        body=body,
    )