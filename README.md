# zendesk-dump

 Dumps Categories, Sections, Articles, Attachments into Markdown and HTML

> P.S. be sure to rename `.env.example` to `.env` and replace dummy values with your own

## Notes

- Attachments will be downloaded by parsing article HTML and downloading it and not via Zendesk Help Center API due to API missing attachments sometimes, parsing HTML more reliable
