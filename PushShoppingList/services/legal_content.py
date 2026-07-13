"""Structured public legal copy for the AI Pantry legal pages."""


LEGAL_EFFECTIVE_DATE = "July 13, 2026"
LEGAL_LAST_UPDATED = "July 13, 2026"
LEGAL_CONTACT_EMAIL = "support@aipantry.app"

# TODO: Finalize with business owner and legal counsel before production launch.
GOVERNING_JURISDICTION = None


def paragraph(text):
    return {"type": "paragraph", "text": text}


def bullet_list(*items):
    return {"type": "list", "items": list(items)}


def subheading(anchor, title):
    return {"type": "heading", "id": anchor, "title": title}


def contact_block(intro):
    return {"type": "contact", "intro": intro, "email": LEGAL_CONTACT_EMAIL}


def governing_law_text():
    if GOVERNING_JURISDICTION:
        return (
            f"These Terms are governed by the laws of {GOVERNING_JURISDICTION}, "
            "without regard to conflict-of-law principles."
        )
    return (
        "These Terms are governed by the laws of the jurisdiction identified by AI Pantry, "
        "without regard to conflict-of-law principles. The final governing jurisdiction will "
        "be listed here before public launch."
    )


TERMS_SECTIONS = [
    {
        "number": 1,
        "id": "eligibility",
        "title": "Eligibility",
        "blocks": [
            paragraph(
                "You must be at least 13 years old, or the minimum legal age required in your "
                "jurisdiction, to use AI Pantry."
            ),
            paragraph(
                "By using AI Pantry, you represent that you have the legal authority to enter "
                "into this agreement."
            ),
        ],
    },
    {
        "number": 2,
        "id": "your-account",
        "title": "Your Account",
        "blocks": [
            paragraph(
                "You are responsible for maintaining the security of your account, keeping your "
                "credentials confidential, and all activity performed through your account."
            ),
            paragraph(
                "AI Pantry uses third-party authentication providers, including Firebase "
                "Authentication. AI Pantry does not store or have access to your authentication "
                "provider password."
            ),
            paragraph(
                "You agree to provide accurate account information and promptly update it when "
                "necessary."
            ),
        ],
    },
    {
        "number": 3,
        "id": "ai-pantry-services",
        "title": "AI Pantry Services",
        "blocks": [
            paragraph("AI Pantry may allow users to:"),
            bullet_list(
                "Import recipes from websites",
                "Import restaurant menus",
                "Upload recipe documents, PDFs, and images",
                "Generate or organize recipes using artificial intelligence",
                "Create cookbooks",
                "Build shopping lists",
                "Track pantry inventory",
                "Plan meals",
                "Compare grocery prices",
                "Store notes and related cooking information",
            ),
            paragraph("Features may be added, changed, suspended, or removed over time."),
        ],
    },
    {
        "number": 4,
        "id": "ai-generated-and-extracted-content",
        "title": "AI-Generated and Extracted Content",
        "blocks": [
            paragraph(
                "AI Pantry uses artificial intelligence and automated extraction tools to "
                "analyze, generate, classify, and organize information."
            ),
            paragraph("AI-generated or extracted information may contain errors, including errors involving:"),
            bullet_list(
                "Ingredients",
                "Quantities",
                "Cooking instructions",
                "Preparation and cooking times",
                "Nutrition estimates",
                "Recipe categories",
                "Dietary labels",
                "Allergy-related information",
                "Restaurant menu information",
                "Product information",
                "Grocery prices",
            ),
            paragraph(
                "You are responsible for reviewing and verifying all generated or extracted "
                "information before relying on it."
            ),
            paragraph(
                "AI Pantry does not guarantee that generated content is accurate, complete, "
                "safe, or suitable for a particular purpose."
            ),
        ],
    },
    {
        "number": 5,
        "id": "food-safety-allergies-nutrition-medical-disclaimer",
        "title": "Food Safety, Allergies, Nutrition, and Medical Disclaimer",
        "blocks": [
            paragraph("AI Pantry is not a medical, nutritional, dietary, or food-safety service."),
            paragraph(
                "Nutrition values, allergen indicators, ingredient substitutions, dietary "
                "classifications, and serving information may be estimates or AI-generated."
            ),
            paragraph(
                "Always verify ingredients, allergens, expiration dates, preparation "
                "temperatures, and food-safety requirements independently."
            ),
            paragraph(
                "Users with allergies, medical conditions, dietary restrictions, or other "
                "health concerns should consult a qualified healthcare or nutrition professional."
            ),
        ],
    },
    {
        "number": 6,
        "id": "prices-store-information-availability",
        "title": "Prices, Store Information, and Availability",
        "blocks": [
            paragraph(
                "Store prices, restaurant prices, product availability, promotions, delivery "
                "options, operating hours, and inventory may change without notice."
            ),
            paragraph(
                "Any price comparison, store status, delivery status, or availability information "
                "provided by AI Pantry is informational and may be delayed or inaccurate."
            ),
            paragraph(
                "The retailer, restaurant, or service provider is the final authority on pricing "
                "and availability."
            ),
        ],
    },
    {
        "number": 7,
        "id": "user-content",
        "title": "User Content",
        "blocks": [
            paragraph(
                "You retain ownership of content you create or upload, including recipes, images, "
                "documents, meal plans, cookbooks, shopping lists, pantry information, and notes."
            ),
            paragraph(
                "You grant AI Pantry a limited, non-exclusive license to host, store, process, "
                "reproduce, display, transform, and analyze your content only as reasonably "
                "necessary to operate, maintain, secure, and improve the service."
            ),
            paragraph(
                "You represent that you have the rights and permissions needed to upload and "
                "process your content."
            ),
        ],
    },
    {
        "number": 8,
        "id": "imported-and-third-party-content",
        "title": "Imported and Third-Party Content",
        "blocks": [
            paragraph(
                "Restaurant names, logos, menu items, trademarks, product names, recipe content, "
                "and other third-party materials remain the property of their respective owners."
            ),
            paragraph(
                "AI Pantry may display or organize third-party content for informational and "
                "personal-use purposes."
            ),
            paragraph(
                "You are responsible for ensuring that your use of imported content complies "
                "with applicable laws and third-party rights."
            ),
        ],
    },
    {
        "number": 9,
        "id": "acceptable-use",
        "title": "Acceptable Use",
        "blocks": [
            paragraph("You may not:"),
            bullet_list(
                "Use AI Pantry for unlawful purposes",
                "Upload malware or harmful code",
                "Attempt unauthorized access",
                "Interfere with or disrupt the service",
                "Circumvent usage limits or security controls",
                "Abuse APIs or automated systems",
                "Scrape the service without permission",
                "Reverse engineer protected portions of the service except where legally permitted",
                "Infringe copyrights, trademarks, privacy rights, or other rights",
                "Impersonate another person",
                "Upload content you do not have permission to use",
                "Use the service to harass, threaten, exploit, or harm others",
            ),
        ],
    },
    {
        "number": 10,
        "id": "guest-and-demo-access",
        "title": "Guest and Demo Access",
        "blocks": [
            paragraph("Guest or demo access may use temporary data and may have limited features."),
            paragraph(
                "Guest data may be reset or deleted at any time and should not be treated as "
                "permanent storage."
            ),
            paragraph("AI Pantry is not responsible for loss of temporary guest data."),
        ],
    },
    {
        "number": 11,
        "id": "third-party-services",
        "title": "Third-Party Services",
        "blocks": [
            paragraph(
                "AI Pantry may rely on third-party providers, including services for authentication, "
                "cloud hosting, file storage, artificial intelligence, maps, analytics, payments, "
                "and communications."
            ),
            paragraph("These providers may have their own terms and privacy policies."),
            paragraph("AI Pantry is not responsible for third-party services outside its control."),
        ],
    },
    {
        "number": 12,
        "id": "paid-plans-and-billing",
        "title": "Paid Plans and Billing",
        "blocks": [
            paragraph(
                "If paid plans are offered, pricing, billing frequency, included features, usage "
                "limits, renewal terms, and cancellation options will be shown before purchase."
            ),
            paragraph(
                "Fees are non-refundable except where required by law or stated otherwise at the "
                "time of purchase."
            ),
            paragraph("AI Pantry may change plan pricing or features with reasonable notice."),
        ],
    },
    {
        "number": 13,
        "id": "availability-and-service-changes",
        "title": "Availability and Service Changes",
        "blocks": [
            paragraph("AI Pantry is provided on an “as available” basis."),
            paragraph(
                "We do not guarantee uninterrupted access, error-free operation, permanent storage, "
                "or continued availability of any feature."
            ),
            paragraph(
                "We may perform maintenance, impose limits, or suspend features for operational or "
                "security reasons."
            ),
        ],
    },
    {
        "number": 14,
        "id": "account-suspension-and-termination",
        "title": "Account Suspension and Termination",
        "blocks": [
            paragraph(
                "We may suspend or terminate access when we reasonably believe a user has violated "
                "these Terms, created security risks, abused the service, failed to pay applicable "
                "fees, or caused harm to AI Pantry or others."
            ),
            paragraph("Users may stop using AI Pantry and request account deletion at any time."),
        ],
    },
    {
        "number": 15,
        "id": "disclaimers",
        "title": "Disclaimers",
        "blocks": [
            paragraph(
                "To the maximum extent permitted by law, AI Pantry is provided “as is” and “as "
                "available,” without warranties of any kind, express or implied."
            ),
            paragraph(
                "We disclaim warranties of merchantability, fitness for a particular purpose, "
                "non-infringement, accuracy, reliability, and availability."
            ),
        ],
    },
    {
        "number": 16,
        "id": "limitation-of-liability",
        "title": "Limitation of Liability",
        "blocks": [
            paragraph(
                "To the maximum extent permitted by law, AI Pantry and its owners, affiliates, "
                "service providers, employees, and contractors will not be liable for indirect, "
                "incidental, special, consequential, exemplary, or punitive damages."
            ),
            paragraph("This includes damages arising from:"),
            bullet_list(
                "Lost recipes or files",
                "Incorrect AI results",
                "Inaccurate nutrition or allergen information",
                "Food preparation decisions",
                "Grocery pricing inaccuracies",
                "Restaurant information inaccuracies",
                "Service interruption",
                "Unauthorized access outside our reasonable control",
                "Loss of profits, data, goodwill, or business opportunities",
            ),
            paragraph(
                "Where liability cannot legally be excluded, total liability will be limited to the "
                "amount paid by the user to AI Pantry during the twelve months before the claim, or "
                "USD $100 if no payment was made, unless applicable law requires otherwise."
            ),
        ],
    },
    {
        "number": 17,
        "id": "indemnification",
        "title": "Indemnification",
        "blocks": [
            paragraph(
                "To the extent permitted by law, you agree to indemnify and hold harmless AI Pantry "
                "and its affiliates from claims arising from your misuse of the service, your "
                "content, or your violation of these Terms or third-party rights."
            ),
        ],
    },
    {
        "number": 18,
        "id": "changes-to-these-terms",
        "title": "Changes to These Terms",
        "blocks": [
            paragraph("We may update these Terms periodically."),
            paragraph(
                "When changes are material, we may provide notice through the application, email, "
                "or another reasonable method."
            ),
            paragraph(
                "Continued use after the updated Terms become effective constitutes acceptance of "
                "the revised Terms."
            ),
        ],
    },
    {
        "number": 19,
        "id": "governing-law",
        "title": "Governing Law",
        "review_required": GOVERNING_JURISDICTION is None,
        "blocks": [paragraph(governing_law_text())],
    },
    {
        "number": 20,
        "id": "contact",
        "title": "Contact",
        "blocks": [contact_block("Questions about these Terms may be sent to:")],
    },
]


PRIVACY_SECTIONS = [
    {
        "number": 1,
        "id": "information-we-collect",
        "title": "Information We Collect",
        "blocks": [
            subheading("account-information", "Account Information"),
            bullet_list(
                "Name",
                "Email address",
                "Profile image",
                "Authentication provider",
                "Account and subscription status",
            ),
            subheading("content-you-provide", "Content You Provide"),
            bullet_list(
                "Recipes",
                "Cookbooks",
                "Shopping lists",
                "Pantry items",
                "Meal plans",
                "Notes",
                "Preferences",
                "Restaurant and store information you save",
            ),
            subheading("uploaded-and-imported-content", "Uploaded and Imported Content"),
            bullet_list(
                "Recipe URLs",
                "Menu URLs",
                "PDFs",
                "Documents",
                "Images",
                "Restaurant menus",
                "Product or barcode information",
            ),
            subheading("technical-and-usage-information", "Technical and Usage Information"),
            bullet_list(
                "IP address",
                "Browser type",
                "Device information",
                "Operating system",
                "Log information",
                "Error and crash data",
                "Feature usage",
                "Approximate location derived from IP, where applicable",
                "Authentication and security events",
            ),
            subheading("payment-information", "Payment Information"),
            paragraph(
                "If paid plans are introduced, payments may be processed by a third-party payment "
                "processor. AI Pantry should not store complete payment-card numbers."
            ),
        ],
    },
    {
        "number": 2,
        "id": "how-we-use-information",
        "title": "How We Use Information",
        "blocks": [
            paragraph("We may use information to:"),
            bullet_list(
                "Provide and operate AI Pantry",
                "Authenticate users",
                "Save and synchronize user content",
                "Import and organize recipes and menus",
                "Generate and improve recipe-related results",
                "Create shopping lists and meal plans",
                "Provide customer support",
                "Detect abuse, fraud, and security threats",
                "Diagnose technical problems",
                "Improve application performance and usability",
                "Communicate service-related updates",
                "Manage subscriptions and billing if paid plans are introduced",
                "Comply with legal obligations",
            ),
        ],
    },
    {
        "number": 3,
        "id": "artificial-intelligence-processing",
        "title": "Artificial Intelligence Processing",
        "blocks": [
            paragraph(
                "Recipes, images, menus, documents, and related content may be processed by "
                "artificial intelligence providers to:"
            ),
            bullet_list(
                "Extract ingredients",
                "Extract cooking instructions",
                "Recognize menu items",
                "Estimate nutrition information",
                "Identify equipment",
                "Categorize recipes",
                "Generate descriptions",
                "Suggest substitutions",
                "Organize shopping and pantry information",
            ),
            paragraph("AI-generated results may be inaccurate and should be reviewed by the user."),
            paragraph(
                "AI Pantry configures its providers and integrations according to the options "
                "available to limit unnecessary use of user content. The exact handling of "
                "submitted content may also be governed by the terms and settings of the "
                "applicable service provider."
            ),
        ],
    },
    {
        "number": 4,
        "id": "authentication",
        "title": "Authentication",
        "blocks": [
            paragraph("AI Pantry may use Firebase Authentication and Google Sign-In."),
            paragraph(
                "Authentication providers may process account identifiers and security information "
                "according to their own privacy policies."
            ),
            paragraph(
                "AI Pantry does not receive or store a user’s Google password or "
                "authentication-provider password."
            ),
        ],
    },
    {
        "number": 5,
        "id": "file-and-data-storage",
        "title": "File and Data Storage",
        "blocks": [
            paragraph(
                "User content may be stored using cloud storage, databases, local development "
                "databases, backup systems, and content-delivery infrastructure."
            ),
            paragraph("This may include providers such as:"),
            bullet_list(
                "Cloudflare",
                "Firebase",
                "Database hosting providers",
                "Application hosting providers",
            ),
        ],
    },
    {
        "number": 6,
        "id": "information-sharing",
        "title": "Information Sharing",
        "blocks": [
            paragraph(
                "AI Pantry may share information with service providers that help operate the "
                "application, including providers for:"
            ),
            bullet_list(
                "Authentication",
                "Artificial intelligence",
                "Hosting",
                "File storage",
                "Error monitoring",
                "Analytics",
                "Email delivery",
                "Payments",
                "Maps or location services",
            ),
            paragraph("AI Pantry does not sell personal information."),
            paragraph(
                "AI Pantry may also disclose information when required by law, to protect users, "
                "investigate abuse, enforce agreements, or complete a business transaction such "
                "as a merger or acquisition."
            ),
        ],
    },
    {
        "number": 7,
        "id": "third-party-links-and-content",
        "title": "Third-Party Links and Content",
        "blocks": [
            paragraph(
                "AI Pantry may link to recipe websites, restaurant websites, grocery retailers, "
                "maps, and other third-party services."
            ),
            paragraph(
                "AI Pantry is not responsible for the privacy practices or content of third-party "
                "websites."
            ),
        ],
    },
    {
        "number": 8,
        "id": "cookies-and-similar-technologies",
        "title": "Cookies and Similar Technologies",
        "blocks": [
            paragraph(
                "AI Pantry may use cookies, browser storage, authentication tokens, and similar "
                "technologies to:"
            ),
            bullet_list(
                "Keep users signed in",
                "Remember preferences",
                "Maintain sessions",
                "Protect account security",
                "Measure application usage",
                "Improve performance",
            ),
        ],
    },
    {
        "number": 9,
        "id": "data-retention",
        "title": "Data Retention",
        "blocks": [
            paragraph(
                "AI Pantry retains information for as long as reasonably necessary to provide the "
                "service, maintain security, comply with legal obligations, resolve disputes, and "
                "enforce agreements."
            ),
            paragraph("User content may remain in backups for a limited period after deletion."),
            paragraph("Guest and demo data may be deleted automatically and without notice."),
        ],
    },
    {
        "number": 10,
        "id": "account-and-data-deletion",
        "title": "Account and Data Deletion",
        "blocks": [
            paragraph(
                "Users may delete individual recipes, lists, files, cookbooks, pantry records, "
                "meal plans, and other supported content through the application where deletion "
                "controls exist."
            ),
            paragraph(
                "Users may request account deletion through account settings or by contacting "
                "support."
            ),
            {"type": "account_deletion"},
        ],
    },
    {
        "number": 11,
        "id": "user-rights-and-choices",
        "title": "User Rights and Choices",
        "blocks": [
            paragraph("Depending on location, users may have rights to:"),
            bullet_list(
                "Access personal information",
                "Correct inaccurate information",
                "Request deletion",
                "Obtain a copy of information",
                "Object to or restrict certain processing",
                "Withdraw consent where processing relies on consent",
                "Appeal certain privacy decisions where required by law",
            ),
            paragraph(f"Requests may be sent to {LEGAL_CONTACT_EMAIL}."),
            paragraph("AI Pantry may need to verify identity before completing a request."),
        ],
    },
    {
        "number": 12,
        "id": "security",
        "title": "Security",
        "blocks": [
            paragraph(
                "AI Pantry uses reasonable administrative, technical, and organizational safeguards "
                "designed to protect user information."
            ),
            paragraph("No online service can guarantee absolute security."),
            paragraph(
                "Users are responsible for protecting their devices, email accounts, and sign-in "
                "credentials."
            ),
        ],
    },
    {
        "number": 13,
        "id": "childrens-privacy",
        "title": "Children’s Privacy",
        "blocks": [
            paragraph("AI Pantry is not directed to children under 13."),
            paragraph("AI Pantry does not knowingly collect personal information from children under 13."),
            paragraph(
                "If AI Pantry learns that such information has been collected, it will take "
                "reasonable steps to delete it."
            ),
        ],
    },
    {
        "number": 14,
        "id": "international-data-transfers",
        "title": "International Data Transfers",
        "blocks": [
            paragraph(
                "Information may be stored or processed in countries other than the user’s country."
            ),
            paragraph(
                "Where required, AI Pantry will use appropriate safeguards for international data "
                "transfers."
            ),
        ],
    },
    {
        "number": 15,
        "id": "state-and-regional-privacy-notices",
        "title": "State and Regional Privacy Notices",
        "blocks": [
            paragraph(
                "Residents of California, Colorado, Connecticut, Virginia, Utah, the European "
                "Economic Area, the United Kingdom, and other jurisdictions may have additional "
                "rights under applicable privacy laws. AI Pantry will respond to verified requests "
                "as required by applicable law."
            ),
        ],
    },
    {
        "number": 16,
        "id": "do-not-sell-or-share",
        "title": "Do Not Sell or Share",
        "blocks": [
            paragraph(
                "AI Pantry does not sell personal information. AI Pantry does not share personal "
                "information for cross-context behavioral advertising as those terms are defined "
                "under applicable California law, unless this policy is updated to disclose such "
                "practices."
            ),
        ],
    },
    {
        "number": 17,
        "id": "changes-to-this-privacy-policy",
        "title": "Changes to This Privacy Policy",
        "blocks": [
            paragraph("AI Pantry may update this Privacy Policy periodically."),
            paragraph(
                "The updated policy will display a revised Effective Date and Last Updated date."
            ),
            paragraph(
                "Material changes may also be communicated through the application or by email."
            ),
        ],
    },
    {
        "number": 18,
        "id": "contact",
        "title": "Contact",
        "blocks": [contact_block("Questions or privacy requests may be sent to:")],
    },
]


LEGAL_DOCUMENTS = {
    "terms": {
        "slug": "terms",
        "short_title": "Terms of Service",
        "title": "AI Pantry Terms of Service",
        "description": "Terms governing access to and use of AI Pantry services.",
        "effective_date": LEGAL_EFFECTIVE_DATE,
        "last_updated": LEGAL_LAST_UPDATED,
        "introduction": [
            "Welcome to AI Pantry (“AI Pantry,” “we,” “our,” or “us”). These Terms of Service "
            "(“Terms”) govern your access to and use of the AI Pantry website, applications, and "
            "related services.",
            "By creating an account, accessing, or using AI Pantry, you agree to these Terms. If "
            "you do not agree, do not use the service.",
        ],
        "sections": TERMS_SECTIONS,
    },
    "privacy": {
        "slug": "privacy",
        "short_title": "Privacy Policy",
        "title": "AI Pantry Privacy Policy",
        "description": "How AI Pantry collects, uses, shares, retains, and protects information.",
        "effective_date": LEGAL_EFFECTIVE_DATE,
        "last_updated": LEGAL_LAST_UPDATED,
        "introduction": [
            "AI Pantry respects your privacy. This Privacy Policy explains what information we "
            "collect, how we use it, when we share it, how long we retain it, and the choices "
            "available to you.",
            "This policy applies to the AI Pantry website, applications, and related services.",
        ],
        "sections": PRIVACY_SECTIONS,
    },
}


def legal_document(slug):
    """Return the structured legal document for a public route."""
    return LEGAL_DOCUMENTS.get(str(slug or "").strip().lower())
