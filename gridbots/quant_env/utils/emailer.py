import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders
import os

class Emailer:
    def __init__(self, smtp_server, port, username, password, use_tls=True):
        self.smtp_server = smtp_server
        self.port = port
        self.username = username
        self.password = password
        self.use_tls = use_tls

    def send(self, to, subject, body, attachments=None):
        msg = MIMEMultipart()
        msg['From'] = self.username
        msg['To'] = to
        msg['Subject'] = subject
        msg.attach(MIMEText(body, 'html'))

        if attachments:
            for filepath in attachments:
                part = MIMEBase('application', 'octet-stream')
                with open(filepath, 'rb') as f:
                    part.set_payload(f.read())
                encoders.encode_base64(part)
                part.add_header('Content-Disposition', f'attachment; filename={os.path.basename(filepath)}')
                msg.attach(part)

        try:
            server = smtplib.SMTP(self.smtp_server, self.port)
            if self.use_tls:
                server.starttls()
            server.login(self.username, self.password)
            server.send_message(msg)
            server.quit()
            print(f"Email sent to {to}")
        except Exception as e:
            print(f"Failed to send email: {e}")