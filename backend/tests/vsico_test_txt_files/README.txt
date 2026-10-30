VSICO ZALO BOT - TEXT TEST FIXTURES
===================================

Structure:
- tests/fixtures/messages/TC-XX_input.txt: input message or scenario
- tests/fixtures/messages/TC-XX_expected.txt: expected behavior/output

Coverage:
- TC-01..TC-05: F1/F2/F3 parsing
- TC-06..TC-08: invalid container/phone/plate cases
- TC-09..TC-12: alias, missing routing data, planning-sheet matching
- TC-13..TC-15: multiple containers, mixed order types, updates
- TC-16..TC-20: non-operational messages, route map, combined-container plan, workbook parsing, multiple return locations

Important:
1. Phone numbers are masked in all fixtures (last six digits hidden).
2. Some cases require a synthetic planning workbook / alias map / route_map fixture to test fully.
3. Expected outputs are based on the provided specification; they are not actual run results.
4. TC-06 container validity should be confirmed by the project's ISO 6346 validator.
5. TC-07's phone length is illustrative because the source number was masked for privacy; use a dedicated synthetic invalid-length value in an isolated parser unit test if exact digit counting is required.
