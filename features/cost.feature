Feature: Cost and time-of-use questions
  As the owner of a home solar installation
  I want to know what my true-up bill might look like under my utility's rate schedule
  So that I can budget for it without waiting for the utility's annual statement

  Background:
    Given today is 2026-08-20 (Pacific)
    And enphase-bridge is reachable

  Scenario: What would my true-up bill look like
    Given the true-up breakdown for 2026-01-01 to 2026-08-18 (Pacific) is:
      | period         | import_kwh | export_kwh | import_cost_usd | export_credit_usd |
      | peak           | 40.0       | 150.0      | 20.00            | 45.00              |
      | off_peak       | 60.0       | 100.0      | 18.00            | 25.00              |
      | super_off_peak | 20.0       | 50.0       | 4.00             | 12.50              |
    When I ask for the true-up estimate from 2026-01-01 to 2026-08-18
    Then the true-up net cost is -40.5 USD
    And the true-up excluded window count is 0
    And the true-up breakdown matches the table
