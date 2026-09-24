"""CycleSafe Symptom Rule Engine - deterministic, non-diagnostic.

Every rule:
- Is a pure function taking a list of cycle records
- Returns a dict with: id, triggered (bool), message, source, urgency
- NEVER names a disease
- Source is 'PENDING clinician/WHO verification' until verified
"""

from dataclasses import dataclass, field
from typing import List, Dict, Optional
from datetime import datetime, date
import numpy as np

@dataclass
class CycleEntry:
    """One cycle record with optional symptom fields."""
    cycle_length_days: float
    start_date: Optional[date] = None
    log_date: Optional[str] = None
    last_period_date: Optional[str] = None
    pain_score: int = 0          # 0=none, 1=mild, 2=moderate, 3=severe
    bleeding_heaviness: int = 0  # 0=light, 1=normal, 2=heavy, 3=very_heavy
    bleeding_days: int = 0
    heavy_soaking_hourly: bool = False  # R2_URGENT indicator
    spotting_between_periods: bool = False
    mood_score: int = 2          # 0=very_low, 1=low, 2=normal, 3=good
    sleep_score: int = 2         # 0=poor, 1=fair, 2=good, 3=excellent
    fatigue_score: int = 0       # 0=none, 1=mild, 2=moderate, 3=severe
    # Perimenopause fields
    hot_flash_count: int = 0
    hot_flash_severity: int = 0  # 0-3
    night_sweats: bool = False
    skipped_period: bool = False

@dataclass 
class RuleResult:
    rule_id: str
    triggered: bool
    message: str
    source: str
    urgency: str  # 'urgent', 'discuss', 'info'
    details: str = ''

RULES_TABLE = [
    {'id': 'R2_URGENT', 'condition': 'soaking pad or tampon every hour for several hours',
     'message': 'If you are soaking through a pad or tampon every hour for several hours, seek urgent medical care.',
     'source': 'PENDING clinician/WHO verification', 'urgency': 'urgent'},
    {'id': 'R1', 'condition': 'severe pain (>=3) in >=3 of last 4 cycles', 
     'message': 'This pain pattern is worth discussing with a healthcare professional.',
     'source': 'PENDING clinician/WHO verification', 'urgency': 'discuss'},
    {'id': 'R2', 'condition': 'heavy bleeding (>=3) in >=3 of last 4 cycles, or bleeding >7 days',
     'message': 'This bleeding pattern is worth discussing with a healthcare professional.',
     'source': 'PENDING clinician/WHO verification', 'urgency': 'discuss'},
    {'id': 'R3', 'condition': '>=2 of last 4 cycles outside 24-38 days',
     'message': 'Your recent cycle lengths fall outside the typical 24-38 day range. This pattern is worth discussing with a healthcare professional.',
     'source': 'PENDING clinician/WHO verification', 'urgency': 'discuss'},
    {'id': 'R4', 'condition': 'no period for >=90 days (not menopause stage)',
     'message': 'No period has been logged for 90+ days. If you are not pregnant or in menopause, this is worth discussing with a healthcare professional.',
     'source': 'PENDING clinician/WHO verification', 'urgency': 'discuss'},
    {'id': 'R5', 'condition': 'low mood (<=1) logged in >=3 of last 4 cycles',
     'message': 'Persistent low mood has been logged across multiple cycles. Consider discussing this with a healthcare professional.',
     'source': 'PENDING clinician/WHO verification', 'urgency': 'discuss'},
    {'id': 'R6', 'condition': 'recent-3 median differs from earlier median by >=3 days',
     'message': 'A change in your typical cycle length has been detected.',
     'source': 'PENDING clinician/WHO verification', 'urgency': 'info'},
    {'id': 'R7_PERI', 'condition': 'hot flashes or night sweats in >=3 of last 4 cycles',
     'message': 'Frequent vasomotor symptoms (hot flashes/night sweats) recorded across recent cycles are worth discussing with a healthcare professional.',
     'source': 'PENDING clinician/WHO verification', 'urgency': 'discuss'},
]

def check_R2_URGENT_extreme_bleeding(entries: List[CycleEntry]) -> RuleResult:
    triggered = any(e.heavy_soaking_hourly for e in entries)
    return RuleResult('R2_URGENT', triggered, RULES_TABLE[0]['message'], RULES_TABLE[0]['source'], 'urgent',
                      'Extremely heavy bleeding requiring hourly pad changes reported')

def check_R1_severe_pain(entries: List[CycleEntry]) -> RuleResult:
    last4 = entries[-4:] if len(entries) >= 4 else entries
    severe_count = sum(1 for e in last4 if e.pain_score >= 3)
    triggered = len(last4) >= 4 and severe_count >= 3
    return RuleResult('R1', triggered, RULES_TABLE[1]['message'], RULES_TABLE[1]['source'], 'discuss',
                      f'{severe_count} of {len(last4)} recent cycles had severe pain')

def check_R2_heavy_bleeding(entries: List[CycleEntry]) -> RuleResult:
    last4 = entries[-4:] if len(entries) >= 4 else entries
    heavy_count = sum(1 for e in last4 if e.bleeding_heaviness >= 3)
    long_bleed = any(e.bleeding_days > 7 for e in last4)
    triggered = (len(last4) >= 4 and heavy_count >= 3) or long_bleed
    return RuleResult('R2', triggered, RULES_TABLE[2]['message'], RULES_TABLE[2]['source'], 'discuss',
                      f'{heavy_count} of {len(last4)} cycles had heavy bleeding; long bleeding: {long_bleed}')

def check_R3_cycle_length_range(entries: List[CycleEntry]) -> RuleResult:
    last4 = entries[-4:] if len(entries) >= 4 else entries
    outside = sum(1 for e in last4 if e.cycle_length_days < 24 or e.cycle_length_days > 38)
    triggered = len(last4) >= 4 and outside >= 2
    return RuleResult('R3', triggered, RULES_TABLE[3]['message'], RULES_TABLE[3]['source'], 'discuss',
                      f'{outside} of {len(last4)} cycles outside 24-38 day range')

def check_R4_absent_period(entries: List[CycleEntry], days_since_last: float = 0, is_menopause: bool = False) -> RuleResult:
    # If days_since_last not explicitly supplied, derive from latest entry date if available
    if days_since_last == 0 and entries:
        today = date.today()
        for e in reversed(entries):
            d_str = e.last_period_date or e.log_date
            if d_str:
                try:
                    dt = datetime.strptime(d_str[:10], "%Y-%m-%d").date()
                    days_since_last = max(0, (today - dt).days)
                    break
                except Exception:
                    pass
            elif e.start_date:
                days_since_last = max(0, (today - e.start_date).days)
                break

    triggered = days_since_last >= 90 and not is_menopause
    return RuleResult('R4', triggered, RULES_TABLE[4]['message'], RULES_TABLE[4]['source'], 'discuss',
                      f'{days_since_last:.0f} days since last period')

def check_R5_low_mood(entries: List[CycleEntry]) -> RuleResult:
    last4 = entries[-4:] if len(entries) >= 4 else entries
    low_count = sum(1 for e in last4 if e.mood_score <= 1)
    triggered = len(last4) >= 4 and low_count >= 3
    return RuleResult('R5', triggered, RULES_TABLE[5]['message'], RULES_TABLE[5]['source'], 'discuss',
                      f'{low_count} of {len(last4)} cycles had low mood')

def check_R6_cycle_shift(entries: List[CycleEntry]) -> RuleResult:
    if len(entries) < 6:
        return RuleResult('R6', False, '', RULES_TABLE[6]['source'], 'info', 'Not enough history')
    lengths = [e.cycle_length_days for e in entries]
    recent3 = np.median(lengths[-3:])
    earlier = np.median(lengths[:-3])
    shift = abs(recent3 - earlier)
    triggered = shift >= 3.0
    return RuleResult('R6', triggered, RULES_TABLE[6]['message'], RULES_TABLE[6]['source'], 'info',
                      f'Recent median {recent3:.1f} vs earlier median {earlier:.1f} (shift {shift:.1f} days)')

def check_R7_perimenopause_vasomotor(entries: List[CycleEntry]) -> RuleResult:
    last4 = entries[-4:] if len(entries) >= 4 else entries
    vaso_count = sum(1 for e in last4 if e.hot_flash_count > 0 or e.night_sweats or e.hot_flash_severity >= 2)
    triggered = len(last4) >= 4 and vaso_count >= 3
    return RuleResult('R7_PERI', triggered, RULES_TABLE[7]['message'], RULES_TABLE[7]['source'], 'discuss',
                      f'{vaso_count} of {len(last4)} recent cycles had vasomotor symptoms')

def run_all_rules(entries: List[CycleEntry], days_since_last: float = 0, is_menopause: bool = False) -> List[RuleResult]:
    results = [
        check_R2_URGENT_extreme_bleeding(entries),
        check_R1_severe_pain(entries),
        check_R2_heavy_bleeding(entries),
        check_R3_cycle_length_range(entries),
        check_R4_absent_period(entries, days_since_last, is_menopause),
        check_R5_low_mood(entries),
        check_R6_cycle_shift(entries),
        check_R7_perimenopause_vasomotor(entries),
    ]
    # Sort by urgency: 'urgent' first, then 'discuss', then 'info'
    urgency_order = {'urgent': 0, 'discuss': 1, 'info': 2}
    results.sort(key=lambda r: urgency_order.get(r.urgency, 3))
    return results

def test_rules():
    # R2_URGENT positive
    urg = [CycleEntry(28, heavy_soaking_hourly=True)]
    assert check_R2_URGENT_extreme_bleeding(urg).triggered == True

    # R1 positive: severe pain in 3 of 4
    pos = [CycleEntry(28, pain_score=3) for _ in range(3)] + [CycleEntry(28, pain_score=1)]
    assert check_R1_severe_pain(pos).triggered == True
    # R1 negative: only 1 severe
    neg = [CycleEntry(28, pain_score=3)] + [CycleEntry(28, pain_score=0) for _ in range(3)]
    assert check_R1_severe_pain(neg).triggered == False
    
    # R2 positive: bleeding > 7 days
    pos2 = [CycleEntry(28, bleeding_days=8)]
    assert check_R2_heavy_bleeding(pos2).triggered == True

    # R3 positive: 2 cycles outside 24-38
    pos3 = [CycleEntry(22), CycleEntry(40), CycleEntry(28), CycleEntry(29)]
    assert check_R3_cycle_length_range(pos3).triggered == True

    # R4 positive: 90 days
    assert check_R4_absent_period([], days_since_last=95).triggered == True
    # R4 negative: menopause
    assert check_R4_absent_period([], days_since_last=95, is_menopause=True).triggered == False

    # R7_PERI positive
    pos7 = [CycleEntry(35, hot_flash_count=2), CycleEntry(40, night_sweats=True), CycleEntry(38, hot_flash_severity=2), CycleEntry(28)]
    assert check_R7_perimenopause_vasomotor(pos7).triggered == True

    print('ALL RULE TESTS PASSED')

if __name__ == '__main__':
    test_rules()
