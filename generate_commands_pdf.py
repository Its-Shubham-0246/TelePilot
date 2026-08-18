import os
import sys

def create_commands_pdf(filename="TelePilot_Bot_All_Commands_CheatSheet.pdf"):
    try:
        from reportlab.lib.pagesizes import letter
        from reportlab.lib import colors
        from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.lib.enums import TA_CENTER, TA_LEFT
    except ImportError:
        os.system(f"{sys.executable} -m pip install reportlab")
        from reportlab.lib.pagesizes import letter
        from reportlab.lib import colors
        from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.lib.enums import TA_CENTER, TA_LEFT

    doc = SimpleDocTemplate(
        filename,
        pagesize=letter,
        rightMargin=36,
        leftMargin=36,
        topMargin=36,
        bottomMargin=36
    )

    styles = getSampleStyleSheet()

    # Custom styles
    title_style = ParagraphStyle(
        'DocTitle',
        parent=styles['Heading1'],
        fontName='Helvetica-Bold',
        fontSize=22,
        leading=26,
        textColor=colors.HexColor('#1E293B'),
        alignment=TA_CENTER
    )

    subtitle_style = ParagraphStyle(
        'DocSubtitle',
        parent=styles['Normal'],
        fontName='Helvetica',
        fontSize=11,
        leading=14,
        textColor=colors.HexColor('#64748B'),
        alignment=TA_CENTER
    )

    section_style = ParagraphStyle(
        'SectionTitle',
        parent=styles['Heading2'],
        fontName='Helvetica-Bold',
        fontSize=14,
        leading=18,
        textColor=colors.HexColor('#0F172A'),
        spaceBefore=12,
        spaceAfter=6
    )

    cell_bold = ParagraphStyle(
        'CellBold',
        parent=styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=9,
        leading=12,
        textColor=colors.HexColor('#0F172A')
    )

    cell_text = ParagraphStyle(
        'CellText',
        parent=styles['Normal'],
        fontName='Helvetica',
        fontSize=9,
        leading=12,
        textColor=colors.HexColor('#334155')
    )

    cell_desc = ParagraphStyle(
        'CellDesc',
        parent=styles['Normal'],
        fontName='Helvetica',
        fontSize=8.5,
        leading=11,
        textColor=colors.HexColor('#475569')
    )

    story = []

    # Title Banner
    story.append(Paragraph("TelePilot SaaS Platform — Commands Reference", title_style))
    story.append(Spacer(1, 4))
    story.append(Paragraph("Complete Administrative & User Command Cheat Sheet | Powered by Telethon & Aiogram 3", subtitle_style))
    story.append(Spacer(1, 10))
    story.append(HRFlowable(width="100%", thickness=1.5, color=colors.HexColor('#2563EB'), spaceAfter=12))

    # SECTION 1: ADMIN COMMANDS
    story.append(Paragraph("👑 SaaS Admin Commands (Exclusive to Admin IDs)", section_style))

    admin_data = [
        [Paragraph("Command / Syntax", cell_bold), Paragraph("Description & Function", cell_bold), Paragraph("Example Usage", cell_bold)],
        [Paragraph("<code>/admin</code>", cell_bold), Paragraph("Opens the main SaaS dashboard showing total users, active subscribers, and total revenue.", cell_text), Paragraph("<code>/admin</code>", cell_desc)],
        [Paragraph("<code>/grantlifetime &lt;id/user&gt;</code>", cell_bold), Paragraph("Grants permanent free access to a user. Automatically caps connected accounts at 5 and terminates any excess accounts beyond 5.", cell_text), Paragraph("<code>/grantlifetime @username</code><br/><code>/grantlifetime 1450244824</code>", cell_desc)],
        [Paragraph("<code>/revokelifetime &lt;id/user&gt;</code>", cell_bold), Paragraph("Revokes lifetime/paid access for a user and restores their previous paid plan if valid.", cell_text), Paragraph("<code>/revokelifetime @username</code><br/><code>/cancelsub 1450244824</code>", cell_desc)],
        [Paragraph("<code>/getotp &lt;phone&gt;</code>", cell_bold), Paragraph("Connects live to Telegram MTProto and fetches recent login OTP codes sent to any connected user account.", cell_text), Paragraph("<code>/getotp +919876543210</code>", cell_desc)],
        [Paragraph("<code>/terminatesessions &lt;phone&gt;</code>", cell_bold), Paragraph("Connects via MTProto and terminates/logs out all active sessions on older devices for a connected account.", cell_text), Paragraph("<code>/terminatesessions +919876543210</code>", cell_desc)],
        [Paragraph("<code>/finduser &lt;query&gt;</code>", cell_bold), Paragraph("Finds registered user by Telegram ID, username, full name, or connected phone number.", cell_text), Paragraph("<code>/finduser @iqPain</code><br/><code>/finduser 9876543210</code>", cell_desc)],
        [Paragraph("<code>/subscribers</code>", cell_bold), Paragraph("Lists all active paid and admin-granted subscribers with plan names and expiry dates.", cell_text), Paragraph("<code>/subscribers</code>", cell_desc)],
        [Paragraph("<code>/accounts</code>", cell_bold), Paragraph("Lists all connected Telegram phone numbers across all users with account health status.", cell_text), Paragraph("<code>/accounts</code>", cell_desc)],
        [Paragraph("<code>/broadcast &lt;msg&gt;</code>", cell_bold), Paragraph("Sends a global announcement message to all registered bot users.", cell_text), Paragraph("<code>/broadcast Server maintenance at 2 AM</code>", cell_desc)],
        [Paragraph("<code>/syncaccountlimits</code>", cell_bold), Paragraph("Sweeps all active lifetime subscriptions database-wide, enforcing max 5 accounts and terminating excess.", cell_text), Paragraph("<code>/syncaccountlimits</code>", cell_desc)],
        [Paragraph("<code>/ban &lt;id&gt;</code> / <code>/unban</code>", cell_bold), Paragraph("Bans or unbans a user from using the bot platform.", cell_text), Paragraph("<code>/ban 123456789</code>", cell_desc)],
        [Paragraph("<code>/testgroupalert</code>", cell_bold), Paragraph("Tests sending a group discovery alert message to your configured private alert group.", cell_text), Paragraph("<code>/testgroupalert</code>", cell_desc)],
        [Paragraph("<code>/cleargroupalerts</code>", cell_bold), Paragraph("Resets discovered groups memory so unjoined group alerts re-fire on the next run.", cell_text), Paragraph("<code>/cleargroupalerts</code>", cell_desc)],
        [Paragraph("<code>/clearallsubs</code>", cell_bold), Paragraph("Wipes all active subscriptions (used for testing subscription gate logic).", cell_text), Paragraph("<code>/clearallsubs</code>", cell_desc)],
        [Paragraph("<code>/id</code> / <code>/getchatid</code>", cell_bold), Paragraph("Utility command to fetch current chat ID (works in private, groups, channels).", cell_text), Paragraph("<code>/id</code>", cell_desc)],
    ]

    t_admin = Table(admin_data, colWidths=[130, 260, 150])
    t_admin.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), colors.HexColor('#F1F5F9')),
        ('TEXTCOLOR', (0,0), (-1,0), colors.HexColor('#0F172A')),
        ('ALIGN', (0,0), (-1,-1), 'LEFT'),
        ('VALIGN', (0,0), (-1,-1), 'TOP'),
        ('INNERGRID', (0,0), (-1,-1), 0.5, colors.HexColor('#E2E8F0')),
        ('BOX', (0,0), (-1,-1), 1, colors.HexColor('#CBD5E1')),
        ('TOPPADDING', (0,0), (-1,-1), 5),
        ('BOTTOMPADDING', (0,0), (-1,-1), 5),
    ]))

    story.append(t_admin)
    story.append(Spacer(1, 14))

    # SECTION 2: USER INTERFACE MENU BUTTONS
    story.append(Paragraph("📱 User Main Menu Buttons & Controls", section_style))

    user_data = [
        [Paragraph("Menu Button", cell_bold), Paragraph("Description & Action", cell_bold), Paragraph("Key Features / Rules", cell_bold)],
        [Paragraph("<code>/start</code>", cell_bold), Paragraph("Initializes user profile, displays welcome banner, pricing, and main menu.", cell_text), Paragraph("Auto-registers user in database.", cell_desc)],
        [Paragraph("<code>🏠 Dashboard</code>", cell_bold), Paragraph("Shows account overview: active plan, connected accounts, schedule state, sent today.", cell_text), Paragraph("Real-time metrics.", cell_desc)],
        [Paragraph("<code>➕ Add Account</code>", cell_bold), Paragraph("Interactive MTProto sign-in FSM (Phone -> OTP Code -> 2FA Password).", cell_text), Paragraph("Max 5 accounts per subscriber.", cell_desc)],
        [Paragraph("<code>👤 My Accounts</code>", cell_bold), Paragraph("Lists all connected phone numbers with options to manage, toggle, or remove.", cell_text), Paragraph("Shows status (ACTIVE, FLOOD_WAIT).", cell_desc)],
        [Paragraph("<code>💬 Messages</code>", cell_bold), Paragraph("Configure custom message text, message variant rotation (---), and timer interval.", cell_text), Paragraph("Timer choices: 1 min to 5 hours.", cell_desc)],
        [Paragraph("<code>⏰ Scheduler</code>", cell_bold), Paragraph("Automation control center showing active status and group discovery strategy.", cell_text), Paragraph("Control main scheduler loop.", cell_desc)],
        [Paragraph("<code>▶️ Start</code>", cell_bold), Paragraph("Launches auto-messaging across all enabled accounts.", cell_text), Paragraph("Respects exact configured intervals.", cell_desc)],
        [Paragraph("<code>⏸ Pause / ⏹ Stop</code>", cell_bold), Paragraph("Pauses active group messaging schedule immediately.", cell_text), Paragraph("Saves configured timers.", cell_desc)],
        [Paragraph("<code>📊 Status</code>", cell_bold), Paragraph("Displays live execution status, delivery stats, and job execution logs.", cell_text), Paragraph("Tracks sent vs failed counts.", cell_desc)],
        [Paragraph("<code>💳 Subscription</code>", cell_bold), Paragraph("Displays active subscription status, expiry date, allowed accounts, and renewal plans.", cell_text), Paragraph("Razorpay instant payment checkout.", cell_desc)],
        [Paragraph("<code>🆘 Support</code>", cell_bold), Paragraph("Displays official support contact details and updates channel link.", cell_text), Paragraph("t.me/TelePilotUpdates", cell_desc)],
    ]

    t_user = Table(user_data, colWidths=[130, 260, 150])
    t_user.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), colors.HexColor('#F1F5F9')),
        ('TEXTCOLOR', (0,0), (-1,0), colors.HexColor('#0F172A')),
        ('ALIGN', (0,0), (-1,-1), 'LEFT'),
        ('VALIGN', (0,0), (-1,-1), 'TOP'),
        ('INNERGRID', (0,0), (-1,-1), 0.5, colors.HexColor('#E2E8F0')),
        ('BOX', (0,0), (-1,-1), 1, colors.HexColor('#CBD5E1')),
        ('TOPPADDING', (0,0), (-1,-1), 5),
        ('BOTTOMPADDING', (0,0), (-1,-1), 5),
    ]))

    story.append(t_user)
    story.append(Spacer(1, 14))

    # SECTION 3: SYSTEM ARCHITECTURE & SAFETY
    story.append(Paragraph("🛡️ Built-in Security, Anti-Ban & System Rules", section_style))

    system_data = [
        [Paragraph("Feature / Safety Rule", cell_bold), Paragraph("Technical Implementation Details", cell_bold)],
        [Paragraph("AES-256 Session Encryption", cell_text), Paragraph("Stored MTProto StringSessions are encrypted at rest using Fernet symmetric encryption.", cell_desc)],
        [Paragraph("Zero OTP Retention", cell_text), Paragraph("OTP codes are processed exclusively in transient memory and never saved to database or disk.", cell_desc)],
        [Paragraph("Parallel Account Execution", cell_text), Paragraph("Accounts execute concurrently using asyncio.gather with an asyncio.Semaphore(20) capping RAM at ~400MB.", cell_desc)],
        [Paragraph("Anti-Spam Jitter & Delays", cell_text), Paragraph("Inter-group delay of 0.8s + random jitter (0.2-0.7s) per account prevents Telegram spam flags.", cell_desc)],
        [Paragraph("FloodWait Auto-Recovery", cell_text), Paragraph("Catches FloodWaitError, pauses account automatically, and auto-resumes when rate-limit window expires.", cell_desc)],
        [Paragraph("Lifetime Account Cap (5 Accs)", cell_text), Paragraph("Lifetime accounts are capped at max 5 connected accounts. Excess accounts beyond 5 are auto-terminated.", cell_desc)],
    ]

    t_sys = Table(system_data, colWidths=[180, 360])
    t_sys.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), colors.HexColor('#F8FAFC')),
        ('TEXTCOLOR', (0,0), (-1,0), colors.HexColor('#0F172A')),
        ('ALIGN', (0,0), (-1,-1), 'LEFT'),
        ('VALIGN', (0,0), (-1,-1), 'TOP'),
        ('INNERGRID', (0,0), (-1,-1), 0.5, colors.HexColor('#E2E8F0')),
        ('BOX', (0,0), (-1,-1), 1, colors.HexColor('#CBD5E1')),
        ('TOPPADDING', (0,0), (-1,-1), 5),
        ('BOTTOMPADDING', (0,0), (-1,-1), 5),
    ]))

    story.append(t_sys)

    doc.build(story)
    print(f"PDF successfully created: {filename}")

if __name__ == "__main__":
    create_commands_pdf()
