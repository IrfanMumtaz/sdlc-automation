<!--
OWNER: Knowledge Base Writer (only)
This file is a SINGLETON — this topic lives here and nowhere else. Feature
docs must link to specific sections here, never restate this content.
The Senior Developer, Automated QA and PO Tester run tests from what this file
says, and a person runs them by hand from "Run it yourself". Every test level
has a row, or N/A with the reason. With several repositories, give each
repository its own rows and name it.
-->

# Pattern: Testing

## When to use
Every change to the product's code.

## Test levels
One row per level `test-scenarios.md` uses. Every test's name starts with its
scenario ID (`FLD-03 rejects an email without @`), so "Run one scenario"
filters by that ID.

| Level | Tool | Location | Needs running | Run the level | Run one scenario |
|---|---|---|---|---|---|
| Field-level (`FLD-`) | {tool} | {where these tests live} | {services, or nothing} | `{command}` | `{command filtering by {ID}}` |
| Unit (`UNIT-`) | {tool} | {location} | {needs} | `{command}` | `{command}` |
| Integration (`INT-`) | {tool} | {location} | {needs} | `{command}` | `{command}` |
| System (`SYS-`) | {tool} | {location} | {needs} | `{command}` | `{command}` |
| End-to-end (`E2E-`) | {tool} | {location} | {needs} | `{command}` | `{command}` |
| UAT (`UAT-`) | {tool} | {location} | {needs} | `{command}` | `{command}` |
| Lint and type check | {tools} | — | {needs} | `{command}` | — |

## What each change must include
| Change | Required tests |
|---|---|
| {kind of change} | {tests it must have} |

## Test data and outside services
- **Test data:** {how tests build their data, e.g. factories, and where they live}
- **Outside services:** {the fakes tests use instead, and where}
- **Time:** {how tests control the clock}

## Run it yourself
{Where to run from, e.g. the repository root.} Set up once, run in order, then
stop what you started.

```
# once
{install dependencies, create the env file}

# start what the tests need
{command}

# every level, in order
{command per level}

# stop
{command}
```

{How to run the same commands without the language runtime installed, if the
project has a container for that.}

## Minimal example
```
{a short test that follows this pattern}
```
