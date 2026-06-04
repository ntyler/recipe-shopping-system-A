# PDF Share Links Manual Test

1. Sign in to the app.
2. Open `/pdfs`.
3. Confirm local PDFs from `PushShoppingList/services/recipe-extractor/data/pdf/` appear.
4. Click `Create Share Link` for one PDF.
5. Copy the generated link.
6. Open the share link in a logged-out or private browser window.
7. Confirm the PDF opens inline.
8. Open `/share/pdf/<token>/download` and confirm the PDF downloads.
9. Revoke the link from `/pdfs`.
10. Confirm the revoked share link no longer opens.
11. Run `git status --short --untracked-files=all` and confirm PDF files and `pdf_share_links.json` are not listed.
