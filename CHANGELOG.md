# Narrative — Changelog

All notable changes will be documented here.

## [Unreleased]
- Redesigned the voting card: no header, reporter and issue type shown as labeled fields, a single row of neutral point buttons, a compact voter line, and a green Reveal button. Revealed results show a bar per value with median and range.
- Show voter avatars on the voting card. Requires the `users:read` bot scope; reinstall the app after adding it. Without it, voters show as @mentions.
- Fetch the Jira issue type (`issuetype`) for the voting card
- Initial open source release
