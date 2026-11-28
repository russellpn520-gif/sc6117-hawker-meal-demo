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

    equipment: Literal["bodyweight", "dumbbells", "gym"] = "bodyweight"
    weekdays: tuple[int, ...] = Field(min_length=1, max_length=7)
    minutes: Literal[10, 20, 30, 45, 60] = 20
    # Profiles saved before split programming retain their existing appointments.
    mode: Literal["strength", "cardio", "mixed"] | None = None
    cardio: Literal["run", "swim", "cycle", "walk"] = "run"
    time_slot: Literal["morning", "afternoon", "evening"] | None = None
    since: date

    @field_validator("weekdays")
    @classmethod
    def valid_weekdays(cls, days):
        if any(day not in range(7) for day in days) or len(days) != len(set(days)):
            raise ValueError("Choose distinct weekdays from Monday (0) to Sunday (6).")
        return tuple(sorted(days))

    def weekly_sessions(self, activity):
        if self.mode is None:
            return dict.fromkeys(self.strength_days(activity), "general")
        days = self.weekdays
        if self.mode == "cardio":
            return dict.fromkeys(days, self.cardio)
        # In mixed schedules spread cardio through the week; for a single available
        # day finish the full-body workout with a short aerobic block.
        cardio_indices = ({len(days) - 1} if self.mode == "mixed" and len(days) >= 2 else set())
        if self.mode == "mixed" and len(days) >= 5:
            cardio_indices.add(2)
        n = len(days) - len(cardio_indices)
        splits = {1: ("full",), 2: ("upper", "lower"), 3: ("push", "pull", "legs")}
        split = splits.get(n, ("chest", "back", "legs", "core"))
        i, result = 0, {}
        for index, day in enumerate(days):
            if index in cardio_indices:
                result[day] = self.cardio
            else:
                result[day] = split[i % len(split)]
                i += 1
        return result

    def strength_days(self, activity):
        """Choose the most spread-out available days, including Sunday/Monday recovery."""
        if self.mode is not None:
            return tuple(d for d, theme in self.weekly_sessions(activity).items() if theme not in CARDIO)
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
    if prefs.mode is not None:
        return destination >= prefs.since
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
            return day.weekday() in prefs.weekly_sessions(self.activity)
        return day >= self.start and (day - self.start).days % 7 in ACTIVITIES[self.activity].training_offsets


THEMES = {
    "rest": ("休息日", "Rest day"), "general": ("训练日", "Training day"),
    "full": ("全身力量", "Full body"), "upper": ("上肢 · 胸背肩", "Upper body · chest, back, shoulders"),
    "lower": ("下肢 · 腿臀", "Lower body"), "push": ("推 · 胸肩与三头", "Push · chest and shoulders"),
    "pull": ("拉 · 背与二头", "Pull · back and biceps"), "legs": ("腿臀日", "Legs and glutes"),
    "chest": ("胸肩日", "Chest and shoulders"), "back": ("练背日", "Back and arms"),
    "core": ("核心与综合", "Core and conditioning"), "run": ("跑步有氧", "Running"),
    "swim": ("游泳有氧", "Swimming"), "cycle": ("骑行有氧", "Cycling"), "walk": ("快走有氧", "Brisk walking"),
}
CARDIO = {"run", "swim", "walk", "cycle"}
LARGE = {"pull", "back", "legs", "lower", "full"}


class TrainingCalendar(set):
    def __init__(self, days, themes=None):
        super().__init__(days)
        self.themes = themes or {}


def training_theme(profile, day, active):
    if day not in active:
        return "rest"
    if theme := getattr(active, "themes", {}).get(day):
        return theme
    prefs = profile.training_for(day)
    return prefs.weekly_sessions(profile.activity).get(day.weekday(), "general") if prefs else "general"


@dataclass(frozen=True)
class DayPlan:
    training: bool
    kcal: tuple[int, int]
    protein_g: int
    carb_g: int = 0
    fat_g: int = 0
    theme: str = "general"
    time_slot: str | None = None

    @property
    def label(self):
        return "训练日" if self.training else "休息日"


def day_plan(profile, day, training_days):
    """Distribute a seven-day maintenance budget without adding exercise twice."""
    start = profile.week_start(day)
    theme = training_theme(profile, day, training_days)
    training = day in training_days
    tier = ACTIVITIES[profile.activity]
    week_themes = [training_theme(profile, d, training_days) for d in training_days
                   if start <= d < start + timedelta(days=7)]
    targets = []
    for resting in profile.resting_kcal:
        average = round(resting * tier.pal * profile.goal_factor)
        step = round(average * 0.08 / 7)
        # Transfer integer energy units between dates, preserving the weekly total.
        uplift = {t: round(step * 1.25) if t in LARGE or t in CARDIO else step for t in THEMES}
        uplift["rest"] = 0
        targets.append(average + 7 * uplift[theme] - sum(uplift[t] for t in week_themes))
    coefficient = max(tier.protein_per_kg, 1.2 if profile.age >= 50 else 0.8)
    if profile.training_for(day) and profile.activity == "regular" and profile.goal_factor != 1:
        # A small demo adjustment for regular strength training during a weight-change goal.
        coefficient = max(coefficient, 1.3)
    protein = round(profile.weight_kg * (coefficient + (0.1 if training else 0)))
    prefs = profile.training_for(day)
    if prefs and prefs.mode and training:
        protein = round(profile.weight_kg * max(coefficient, 1.4 if theme in CARDIO else 1.6))
    energy = sum(targets) / 2
    fat_share = 0.26 if theme in CARDIO else 0.28 if theme in LARGE else 0.30 if training else 0.34
    fat = max(0, round(energy * fat_share / 9))
    carbs = max(0, round((energy - protein * 4 - fat * 9) / 4))
    return DayPlan(training, tuple(targets), protein, carbs, fat, theme, prefs.time_slot if prefs and training else None)


def span(values):
    low, high = (round(n) for n in values)
    return str(low) if low == high else f"{low}–{high}"


def move_targets(profile, origin, destination, active):
    themes = dict(getattr(active, "themes", {}))
    themes[destination] = training_theme(profile, origin, active)
    proposed = TrainingCalendar((active - {origin}) | {destination}, themes)
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
