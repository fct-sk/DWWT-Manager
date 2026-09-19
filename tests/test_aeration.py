"""Tests for aeration configuration strategies."""
import pytest
from custom_components.dwwt_manager.aeration import (
    AerationContext, HeuristicAerationStrategyV1, ManualAerationStrategy,
    NoHouseholdAdaptation, calculate_final_schedule,
)
from custom_components.dwwt_manager.const import AerationConfiguration, OperatingMode

REFERENCE = AerationContext(3000, 60, 6)

def test_manual_aeration_preserves_values_for_all_modes():
    values = {mode.value: {"on": index + 11, "off": index + 21} for index, mode in enumerate(OperatingMode)}
    strategy = ManualAerationStrategy(values)
    for index, mode in enumerate(OperatingMode):
        result = strategy.calculate(mode, REFERENCE)
        assert (result.on_minutes, result.off_minutes) == (index + 11, index + 21)

def test_automatic_reference_6eo_and_2eo():
    strategy = HeuristicAerationStrategyV1()
    six = strategy.calculate(OperatingMode.NORMAL, REFERENCE)
    two = strategy.calculate(OperatingMode.NORMAL, AerationContext(3000, 60, 2))
    assert (six.on_minutes, six.off_minutes) == (240, 240)
    assert (two.on_minutes, two.off_minutes) == (80, 400)
    assert six.source == "heuristic_v1"

def test_eco_reference_is_10_470():
    result = HeuristicAerationStrategyV1().calculate(OperatingMode.ECO, REFERENCE)
    assert (result.on_minutes, result.off_minutes) == (10, 470)

def test_pipeline_has_inactive_household_adaptation():
    result = calculate_final_schedule(
        HeuristicAerationStrategyV1(), NoHouseholdAdaptation(),
        OperatingMode.NORMAL, REFERENCE,
    )
    assert (result.on_minutes, result.off_minutes) == (240, 240)

def test_manufacturer_configuration_is_modeled_but_not_selectable():
    assert AerationConfiguration.MANUFACTURER_CONFIGURATION.value == "manufacturer_configuration"
    selectable = [AerationConfiguration.MANUAL, AerationConfiguration.AUTOMATIC]
    assert AerationConfiguration.MANUFACTURER_CONFIGURATION not in selectable

def test_invalid_automatic_inputs_are_rejected():
    with pytest.raises(ValueError):
        HeuristicAerationStrategyV1().calculate(OperatingMode.NORMAL, AerationContext(3000, 0, 6))
