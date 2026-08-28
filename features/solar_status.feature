Feature: Solar status questions
  As the owner of a home solar installation
  I want to ask the MCP tools plain questions about my solar system
  So that I know how it's performing without reading raw bridge data

  Background:
    Given today is 2026-06-15 (Pacific)
    And enphase-bridge is reachable

  Scenario: How is my solar right now
    Given the bridge's latest energy window started 10 minutes ago producing 900.0 Wh and consuming 400.0 Wh
    And the bridge's most recent power sample reads 1200.0 W production, 800.0 W consumption, -400.0 W grid
    And the bridge has been up for 12345 seconds
    And today's energy windows (Pacific) are:
      | wh_produced | wh_consumed | wh_grid_export |
      | 1000.0      | 400.0       | 300.0          |
      | 1500.0      | 600.0       | 500.0          |
    When I ask for the current solar status
    Then the system is reported online
    And the instantaneous production is 1200.0 W
    And today's produced energy is 2.5 kWh
    And today's consumed energy is 1.0 kWh

  Scenario: How much did I produce today
    Given yesterday's energy windows (Pacific) are:
      | wh_produced | wh_consumed | wh_grid_export | is_complete |
      | 500.0       | 300.0       | 200.0           | true        |
      | 600.0       | 300.0       | 300.0           | true        |
      | 700.0       | 300.0       | 400.0           | true        |
      | 800.0       | 300.0       | 500.0           | false       |
    When I ask for yesterday's daily summary
    Then the produced energy is 2.6 kWh
    And the consumed energy is 1.2 kWh
    And the net energy is 1.4 kWh
    And the data completeness is 3.12 percent

  Scenario: Today vs yesterday
    Given today's energy windows (Pacific) are:
      | wh_produced | wh_consumed | wh_grid_export |
      | 1000.0      | 500.0       | 300.0          |
      | 1500.0      | 700.0       | 400.0          |
    And yesterday's energy windows (Pacific) are:
      | wh_produced | wh_consumed | wh_grid_export |
      | 800.0       | 600.0       | 100.0          |
      | 1200.0      | 600.0       | 200.0          |
    When I compare today to yesterday
    Then day A's produced energy is 2.5 kWh
    And day B's produced energy is 2.0 kWh
    And the produced energy difference is 0.5 kWh
    And the produced energy percent difference is 25.0 percent
