# Narrative — Changelog

All notable changes will be documented here.

## [Unreleased]
- Redesigned the voting card: no header, reporter and issue type shown as labeled fields, a single row of neutral point buttons, a compact voter line, and a green Reveal button. Revealed results show a bar per value with median and range.
- Optional voter avatars on the voting card, off by default. Turn on per channel in `/point-config` or org-wide with `SHOW_VOTER_AVATARS`; needs the `users:read` bot scope. When off, voters show as @mentions.
- `/point-config` modal: settings grouped under Jira connection, Pointing and Voting card, with shorter field hints
- Fetch the Jira issue type (`issuetype`) for the voting card
- Initial open source release
