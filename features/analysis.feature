Feature: Multi-day analysis questions
  As the owner of a home solar installation
  I want to ask about longer stretches of time and my equipment's health
  So that I can spot trends and problems without reading raw bridge data

  Background:
    Given today is 2026-06-20 (Pacific)
    And enphase-bridge is reachable

  Scenario: How did last week compare to the week before
    Given the energy windows (Pacific) starting 2026-06-08 are:
      | wh_produced | wh_consumed | wh_grid_export |
      | 1000.0      | 500.0       | 300.0          |
      | 1500.0      | 700.0       | 400.0          |
    And the energy windows (Pacific) starting 2026-06-01 are:
      | wh_produced | wh_consumed | wh_grid_export |
      | 800.0       | 600.0       | 100.0          |
      | 1200.0      | 600.0       | 200.0          |
    When I compare the period 2026-06-08 to 2026-06-14 against the period 2026-06-01 to 2026-06-07
    Then period A's produced energy is 2.5 kWh
    And period B's produced energy is 2.0 kWh
    And the period produced energy difference is 0.5 kWh
    And the period produced energy percent difference is 25.0 percent

  Scenario: Are any of my inverters having problems
    Given the bridge's inverter arrays are:
      | array | serial       | watts_output | is_online |
      | east  | 121847012345 | 425.0        | true      |
      | east  | 121847012346 | 0.0          | false     |
      | west  | 121847099999 | 300.0        | true      |
    When I ask whether any inverters need attention
    Then 1 inverter needs attention
    And the inverter needing attention has serial 121847012346 in array east
