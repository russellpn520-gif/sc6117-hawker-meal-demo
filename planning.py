from dataclasses import dataclass
from datetime import date, timedelta
from itertools import combinations
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


@dataclass(frozen=True)
class Activity:
    label: str
    pal: float
    protein_per_kg: float
    training_offsets: tuple[int, ...]
    advice: str
    recovery: str


ACTIVITIES = {
    "inactive": Activity("没有运动习惯 · 通常每周 0 天", 1.20, 0.8, (0,),
                         "今天可以从饭后舒适步行 10 分钟开始，习惯后再慢慢延长。",
                         "今天按平时节奏活动，有空起身走一走。"),
    "occasional": Activity("偶尔活动 · 通常每周 1–2 天", 1.375, 1.0, (0, 3),
                           "今天试试快走 20 分钟，选能说话的步速，时间也可以拆开。",
                           "今天可以轻松散步，给下一次活动留些体力。"),
    "regular": Activity("经常活动 · 通常每周至少 3 天", 1.50, 1.2, (0, 2, 4),
                        "今天做一次熟悉的有氧或力量练习。和上次交替，给同一肌群留出恢复时间。",
                        "今天安排恢复，轻松散步即可，下次训练再回到平时的强度。"),
    "athlete": Activity("专业运动员 · 系统备赛，通常每周超过 12 小时", 1.90, 1.5, (0, 2, 3, 4, 5, 6),
                        "沿用教练安排的专项训练，把日历对齐实际训练日。高训练量时请与运动营养师核对摄入。",
                        "把今天留给教练计划中的恢复活动，按实际训练周期调整安排。"),
}
GOALS = {"maintain": "维持体重", "lose": "温和减脂", "gain": "温和增重"}
SEXES = {"female": "女性", "male": "男性"}


class TrainingPreferences(BaseModel):
    model_config = ConfigDict(frozen=True)

    equipment: Literal["bodyweight", "dumbbells"] = "bodyweight"
    weekdays: tuple[int, ...] = Field(min_length=1, max_length=7)
    minutes: Literal[10, 20, 30] = 20
    since: date

    @field_validator("weekdays")
    @classmethod
    def valid_weekdays(cls, days):
        if any(day not in range(7) for day in days) or len(days) != len(set(days)):
            raise ValueError("Choose distinct weekdays from Monday (0) to Sunday (6).")
        return tuple(sorted(days))

    def strength_days(self, activity):
        """Choose the most spread-out available days, including Sunday/Monday recovery."""
        limit = min(3, len(ACTIVITIES[activity].training_offsets), len(self.weekdays))
        for count in range(limit, 0, -1):
            best = None
            best_gap = 1
            for candidate in combinations(self.weekdays, count):
                gaps = [b - a for a, b in zip(candidate, candidate[1:])]
                smallest = min([7 + candidate[0] - candidate[-1], *gaps])
                if smallest > best_gap:
                    best, best_gap = candidate, smallest
            if best is not None:
                return best
        return ()


def valid_training_move(profile, origin, destination, neighbors):
    prefs = profile.training
    if not prefs or destination < prefs.since:
        return True
    return (destination.weekday() in prefs.weekdays
            and destination - timedelta(days=1) not in neighbors
            and destination + timedelta(days=1) not in neighbors)


class Profile(BaseModel):
    model_config = ConfigDict(frozen=True, str_strip_whitespace=True, allow_inf_nan=False)

    nickname: str = Field(default="", max_length=24)
    age: int = Field(ge=18, le=115)
    height_cm: float = Field(ge=80, le=250)
    weight_kg: float = Field(ge=20, le=400)
    activity: Literal["inactive", "occasional", "regular", "athlete"]
    sex: Literal["female", "male"] | None = None
    goal: Literal["maintain", "lose", "gain"] = "maintain"
    start: date
    training: TrainingPreferences | None = None
    training_history: tuple[TrainingPreferences, ...] = ()

    @property
    def goal_factor(self):
        if self.activity == "athlete":
            return 1.0
        if self.goal == "lose" and self.weight_kg / (self.height_cm / 100) ** 2 >= 18.5:
            return 0.95
        return 1.05 if self.goal == "gain" else 1.0

    @property
    def resting_kcal(self):
        base = 10 * self.weight_kg + 6.25 * self.height_cm - 5 * self.age
        offsets = {"female": -161, "male": 5}
        if self.sex:
            value = base + offsets[self.sex]
            return value, value
        return base + offsets["female"], base + offsets["male"]

    def week_start(self, day):
        return day - timedelta(days=(day - self.start).days % 7)

    def training_for(self, day):
        if self.training and day >= self.training.since:
            return self.training
        return next((p for p in reversed(self.training_history) if day >= p.since), None)

    def scheduled_by_default(self, day):
        if prefs := self.training_for(day):
            return day.weekday() in prefs.strength_days(self.activity)
        return day >= self.start and (day - self.start).days % 7 in ACTIVITIES[self.activity].training_offsets


@dataclass(frozen=True)
class DayPlan:
    training: bool
    kcal: tuple[int, int]
    protein_g: int

    @property
    def label(self):
        return "训练日" if self.training else "休息日"


def day_plan(profile, day, training_days):
    """Distribute a seven-day maintenance budget without adding exercise twice."""
    start = profile.week_start(day)
    count = sum(start <= d < start + timedelta(days=7) for d in training_days)
    training = day in training_days
    tier = ACTIVITIES[profile.activity]
    targets = []
    for resting in profile.resting_kcal:
        average = round(resting * tier.pal * profile.goal_factor)
        step = round(average * 0.08 / 7)
        targets.append(average + (7 * int(training) - count) * step)
    coefficient = max(tier.protein_per_kg, 1.2 if profile.age >= 50 else 0.8)
    if profile.training_for(day) and profile.activity == "regular" and profile.goal_factor != 1:
        # A small demo adjustment for regular strength training during a weight-change goal.
        coefficient = max(coefficient, 1.3)
    protein = round(profile.weight_kg * (coefficient + (0.1 if training else 0)))
    return DayPlan(training, tuple(targets), protein)


def span(values):
    low, high = (round(n) for n in values)
    return str(low) if low == high else f"{low}–{high}"


def move_targets(profile, origin, destination, active):
    proposed = (active - {origin}) | {destination}
    return tuple((day_plan(profile, day, active), day_plan(profile, day, proposed))
                 for day in (origin, destination))


def calorie_balance(targets, eaten):
    low, high = targets
    if eaten > high:
        return "已超出今日目标", f"{eaten - high:.0f} kcal"
    if eaten >= low:
        return "今日热量", "已达目标" if low == high else "已在目标范围"
    if low == high:
        return "今天还差", f"{low - eaten:.0f} kcal"
    return "距今日目标下限", f"{low - eaten:.0f} kcal"
