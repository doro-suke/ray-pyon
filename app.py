import streamlit as st
import pandas as pd
import jpholiday
from ortools.sat.python import cp_model
import calendar
from datetime import datetime
from streamlit_local_storage import LocalStorage

# --- シフト作成のコアロジック（変更なし） ---
def create_shift_schedule(year, month, staff_names, holiday_requests, work_requests, nikkin_requirements, fixed_shifts):
    staff_count = len(staff_names)
    works = {"公休": 0, "日勤": 1, "半日": 2, "当直": 3, "明け": 4}
    works_inv = {v: k for k, v in works.items()}
    try:
        num_days = calendar.monthrange(year, month)[1]
    except calendar.IllegalMonthError:
        st.error("有効な月を入力してください（1-12）。")
        return None, None
    dates = [pd.Timestamp(f"{year}-{month}-{d}") for d in range(1, num_days + 1)]
    holidays = [d[0].day for d in jpholiday.month_holidays(year, month)]
    model = cp_model.CpModel()
    shifts = {}
    for s_idx in range(staff_count):
        for d_idx in range(num_days):
            shifts[(s_idx, d_idx)] = model.NewIntVar(0, len(works) - 1, f"shift_s{s_idx}_d{d_idx}")
    for d_idx, date in enumerate(dates):
        is_on_duty = [model.NewBoolVar(f'd{d_idx}_s{s_idx}_is_duty') for s_idx in range(staff_count)]
        for s_idx in range(staff_count):
            model.Add(shifts[(s_idx, d_idx)] == works["当直"]).OnlyEnforceIf(is_on_duty[s_idx])
            model.Add(shifts[(s_idx, d_idx)] != works["当直"]).OnlyEnforceIf(is_on_duty[s_idx].Not())
        model.Add(sum(is_on_duty) == 1)
        required_nikkin = nikkin_requirements[date.weekday()]
        if required_nikkin > 0:
            is_on_nikkin = [model.NewBoolVar(f'd{d_idx}_s{s_idx}_is_nikkin') for s_idx in range(staff_count)]
            for s_idx in range(staff_count):
                model.Add(shifts[(s_idx, d_idx)] == works["日勤"]).OnlyEnforceIf(is_on_nikkin[s_idx])
                model.Add(shifts[(s_idx, d_idx)] != works["日勤"]).OnlyEnforceIf(is_on_nikkin[s_idx].Not())
            model.Add(sum(is_on_nikkin) == required_nikkin)
    for s_idx in range(staff_count):
        model.Add(shifts[(s_idx, 0)] != works["明け"])
        for d_idx in range(num_days):
            is_duty_today = model.NewBoolVar(f's{s_idx}_d{d_idx}_is_duty_c2')
            model.Add(shifts[(s_idx, d_idx)] == works["当直"]).OnlyEnforceIf(is_duty_today)
            model.Add(shifts[(s_idx, d_idx)] != works["当直"]).OnlyEnforceIf(is_duty_today.Not())
            is_ake_today = model.NewBoolVar(f's{s_idx}_d{d_idx}_is_ake_c2')
            model.Add(shifts[(s_idx, d_idx)] == works["明け"]).OnlyEnforceIf(is_ake_today)
            model.Add(shifts[(s_idx, d_idx)] != works["明け"]).OnlyEnforceIf(is_ake_today.Not())
            if d_idx > 0:
                was_duty_yesterday = model.NewBoolVar(f's{s_idx}_d{d_idx-1}_was_duty_c2')
                model.Add(shifts[(s_idx, d_idx - 1)] == works["当直"]).OnlyEnforceIf(was_duty_yesterday)
                model.Add(shifts[(s_idx, d_idx - 1)] != works["当直"]).OnlyEnforceIf(was_duty_yesterday.Not())
                model.AddImplication(is_ake_today, was_duty_yesterday)
            if d_idx < num_days - 1:
                is_ake_tomorrow = model.NewBoolVar(f's{s_idx}_d{d_idx+1}_is_ake_c2')
                model.Add(shifts[(s_idx, d_idx+1)] == works["明け"]).OnlyEnforceIf(is_ake_tomorrow)
                model.Add(shifts[(s_idx, d_idx+1)] != works["明け"]).OnlyEnforceIf(is_ake_tomorrow.Not())
                model.AddImplication(is_duty_today, is_ake_tomorrow)
            if d_idx < num_days - 1:
                is_off_tomorrow = model.NewBoolVar(f's{s_idx}_d{d_idx+1}_is_off_c2')
                model.Add(shifts[(s_idx, d_idx+1)] == works["公休"]).OnlyEnforceIf(is_off_tomorrow)
                model.Add(shifts[(s_idx, d_idx+1)] != works["公休"]).OnlyEnforceIf(is_off_tomorrow.Not())
                model.AddImplication(is_ake_today, is_off_tomorrow)
    max_consecutive_days = 4
    for s_idx in range(staff_count):
        for d_idx in range(num_days - max_consecutive_days):
            is_off_in_window = [model.NewBoolVar(f's{s_idx}_d{i}_is_off') for i in range(d_idx, d_idx + max_consecutive_days + 1)]
            for i, day_index in enumerate(range(d_idx, d_idx + max_consecutive_days + 1)):
                model.Add(shifts[(s_idx, day_index)] == works["公休"]).OnlyEnforceIf(is_off_in_window[i])
                model.Add(shifts[(s_idx, day_index)] != works["公休"]).OnlyEnforceIf(is_off_in_window[i].Not())
            model.Add(sum(is_off_in_window) >= 1)
    for s_idx, s_name in enumerate(staff_names):
        for day_off in holiday_requests.get(s_name, []):
            if 1 <= day_off <= num_days:
                model.Add(shifts[(s_idx, day_off - 1)] == works["公休"])
        for day_on in work_requests.get(s_name, []):
            if 1 <= day_on <= num_days:
                model.Add(shifts[(s_idx, day_on - 1)] != works["公休"])
    for fix in fixed_shifts:
        s_name = fix['staff']
        day = fix['day']
        work = fix['work']
        if s_name in staff_names:
            s_idx = staff_names.index(s_name)
            d_idx = day - 1
            work_id = works.get(work)
            if work_id is not None:
                model.Add(shifts[(s_idx, d_idx)] == work_id)
    for s_idx in range(staff_count):
        work_days_bools = [model.NewBoolVar(f's{s_idx}_d{d_idx}_is_work') for d_idx in range(num_days)]
        for d_idx in range(num_days):
            model.Add(shifts[(s_idx, d_idx)] != works["公休"]).OnlyEnforceIf(work_days_bools[d_idx])
            model.Add(shifts[(s_idx, d_idx)] == works["公休"]).OnlyEnforceIf(work_days_bools[d_idx].Not())
        model.Add(sum(work_days_bools) == num_days - 10)
    duty_counts = [model.NewIntVar(0, num_days, f"duty_{s_idx}") for s_idx in range(staff_count)]
    holiday_work_counts = [model.NewIntVar(0, num_days, f"holiday_work_{s_idx}") for s_idx in range(staff_count)]
    for s_idx in range(staff_count):
        is_duty_bools = [model.NewBoolVar(f's{s_idx}_d{d_idx}_is_duty_count') for d_idx in range(num_days)]
        for d_idx in range(num_days):
            model.Add(shifts[(s_idx, d_idx)] == works["当直"]).OnlyEnforceIf(is_duty_bools[d_idx])
            model.Add(shifts[(s_idx, d_idx)] != works["当直"]).OnlyEnforceIf(is_duty_bools[d_idx].Not())
        model.Add(duty_counts[s_idx] == sum(is_duty_bools))
        holiday_indices = [d_idx for d_idx, date in enumerate(dates) if date.weekday() == 6 or date.day in holidays]
        if holiday_indices:
            is_holiday_work_bools = [model.NewBoolVar(f's{s_idx}_d{d_idx}_is_hwork') for d_idx in holiday_indices]
            for i, d_idx in enumerate(holiday_indices):
                 model.Add(shifts[(s_idx, d_idx)] != works["公休"]).OnlyEnforceIf(is_holiday_work_bools[i])
                 model.Add(shifts[(s_idx, d_idx)] == works["公休"]).OnlyEnforceIf(is_holiday_work_bools[i].Not())
            model.Add(holiday_work_counts[s_idx] == sum(is_holiday_work_bools))
        else:
            model.Add(holiday_work_counts[s_idx] == 0)
    min_duty, max_duty = model.NewIntVar(0, 10, 'min_d'), model.NewIntVar(0, 10, 'max_d')
    min_holi, max_holi = model.NewIntVar(0, 10, 'min_h'), model.NewIntVar(0, 10, 'max_h')
    model.AddMinEquality(min_duty, duty_counts)
    model.AddMaxEquality(max_duty, duty_counts)
    model.AddMinEquality(min_holi, holiday_work_counts)
    model.AddMaxEquality(max_holi, holiday_work_counts)
    model.Minimize((max_duty - min_duty) + (max_holi - min_holi))
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = 30.0
    status = solver.Solve(model)
    if status == cp_model.OPTIMAL or status == cp_model.FEASIBLE:
        schedule = {}
        for s_idx, s_name in enumerate(staff_names):
            schedule
