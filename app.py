import streamlit as st
import pandas as pd
import jpholiday
from ortools.sat.python import cp_model
import calendar
from datetime import datetime

# --- シフト作成のコアロジック（関数として定義） ---
def create_shift_schedule(year, month, staff_names, holiday_requests, work_requests, nikkin_requirements):
    """
    与えられた条件でシフトを計算する関数
    """
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

    # --- 制約 ---
    # C1: 必要人数
    for d_idx, date in enumerate(dates):
        # 当直は毎日1人
        is_on_duty = [model.NewBoolVar(f'd{d_idx}_s{s_idx}_is_duty') for s_idx in range(staff_count)]
        for s_idx in range(staff_count):
            model.Add(shifts[(s_idx, d_idx)] == works["当直"]).OnlyEnforceIf(is_on_duty[s_idx])
            model.Add(shifts[(s_idx, d_idx)] != works["当直"]).OnlyEnforceIf(is_on_duty[s_idx].Not())
        model.Add(sum(is_on_duty) == 1)
        
        # 曜日ごとの日勤人数ルール
        required_nikkin = nikkin_requirements[date.weekday()]
        if required_nikkin > 0:
            is_on_nikkin = [model.NewBoolVar(f'd{d_idx}_s{s_idx}_is_nikkin') for s_idx in range(staff_count)]
            for s_idx in range(staff_count):
                model.Add(shifts[(s_idx, d_idx)] == works["日勤"]).OnlyEnforceIf(is_on_nikkin[s_idx])
                model.Add(shifts[(s_idx, d_idx)] != works["日勤"]).OnlyEnforceIf(is_on_nikkin[s_idx].Not())
            model.Add(sum(is_on_nikkin) == required_nikkin)
        
        # ▼▼▼【修正点】祝日に関する古いルールを削除しました ▼▼▼
        # このセクションを削除することで、祝日や日曜日にも日勤を割り当てられるようになります。
        # ▲▲▲ 修正完了 ▲▲▲

    # C2: 当直→明け→公休ルール
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

    # C3: 連続勤務
    max_consecutive_days = 4
    for s_idx in range(staff_count):
        for d_idx in range(num_days - max_consecutive_days):
            is_off_in_window = [model.NewBoolVar(f's{s_idx}_d{i}_is_off') for i in range(d_idx, d_idx + max_consecutive_days + 1)]
            for i, day_index in enumerate(range(d_idx, d_idx + max_consecutive_days + 1)):
                model.Add(shifts[(s_idx, day_index)] == works["公休"]).OnlyEnforceIf(is_off_in_window[i])
                model.Add(shifts[(s_idx, day_index)] != works["公休"]).OnlyEnforceIf(is_off_in_window[i].Not())
            model.Add(sum(is_off_in_window) >= 1)

    # C4: 希望休 & 出勤希望
    for s_idx, s_name in enumerate(staff_names):
        for day_off in holiday_requests.get(s_name, []):
            if 1 <= day_off <= num_days:
                model.Add(shifts[(s_idx, day_off - 1)] == works["公休"])
        for day_on in work_requests.get(s_name, []):
            if 1 <= day_on <= num_days:
                model.Add(shifts[(s_idx, day_on - 1)] != works["公休"])

    # C5: 総勤務日数
    for s_idx in range(staff_count):
        work_days_bools = [model.NewBoolVar(f's{s_idx}_d{d_idx}_is_work') for d_idx in range(num_days)]
        for d_idx in range(num_days):
            model.Add(shifts[(s_idx, d_idx)] != works["公休"]).OnlyEnforceIf(work_days_bools[d_idx])
            model.Add(shifts[(s_idx, d_idx)] == works["公休"]).OnlyEnforceIf(work_days_bools[d_idx].Not())
        model.Add(sum(work_days_bools) == num_days - 10)

    # C6: 公平性
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
            schedule[s_name] = [works_inv[solver.Value(shifts[(s_idx, d_idx)])] for d_idx in range(num_days)]
        df = pd.DataFrame(schedule).T
        weekdays_jp = ["月", "火", "水", "木", "金", "土", "日"] df.columns = [f"{date.day} ({weekdays_jp[date.weekday()]})" for date in dates]
        return df, "success"
    else:
        return None, "failed"

# --- ここからがStreamlitのUI部分 ---
st.set_page_config(page_title="レイぴょん", layout="wide")
st.title("🏥 レイぴょん - シフト自動作成")

st.header("1. 基本設定")
col1, col2, col3 = st.columns(3)
with col1:
    year = st.number_input("対象年", min_value=2024, max_value=2030, value=datetime.now().year)
with col2:
    month = st.number_input("対象月", min_value=1, max_value=12, value=datetime.now().month)
with col3:
    staff_count = st.number_input("スタッフ人数", min_value=1, max_value=20, value=6, key="staff_count")

st.header("2. スタッフの名前")
default_names = ["山田", "鈴木", "佐藤", "田中", "高橋", "渡辺", "伊藤", "山本", "中村", "小林",
                 "加藤", "吉田", "山口", "松本", "井上", "木村", "林", "佐々木", "清水", "山崎"]
staff_names = []
name_cols = st.columns(2)
for i in range(staff_count):
    with name_cols[i % 2]:
        staff_names.append(
            st.text_input(f"スタッフ {i+1}の名前", value=default_names[i] if i < len(default_names) else f"スタッフ{i+1}", key=f"name_{i}")
        )

st.header("3. 曜日ごとの日勤人数")
weekdays = ["月", "火", "水", "木", "金", "土", "日"]
cols = st.columns(7)
nikkin_requirements = []
for i, day in enumerate(weekdays):
    with cols[i]:
        default_val = 1 if day == "金" else 0 if day in ["土", "日"] else 2
        # ラベルを漢字一文字に変更
        nikkin_requirements.append(st.number_input(day, min_value=0, max_value=staff_count, value=default_val, key=f"nikkin_{i}"))
        
st.header("4. スタッフごとの希望")
holiday_requests = {}
work_requests = {}
all_days = list(range(1, calendar.monthrange(year, month)[1] + 1))

num_columns = 3
cols = st.columns(num_columns)
for i, name in enumerate(staff_names):
    with cols[i % num_columns]:
        with st.expander(f"**{name}さんの希望**", expanded=True):
            holiday_requests[name] = st.multiselect(
                "希望休", options=all_days, key=f"h_{i}"
            )
            work_requests[name] = st.multiselect(
                "出勤希望", options=all_days, key=f"w_{i}"
            )

st.header("5. シフト作成")
if st.button("🚀 シフトを作成する", type="primary"):
    if len(staff_names) != len(set(staff_names)):
        st.error("エラー: スタッフの名前が重複しています。それぞれ違う名前にしてください。")
    else:
        with st.spinner("最適なシフトを計算中です..."):
            df, status = create_shift_schedule(year, month, staff_names, holiday_requests, work_requests, nikkin_requirements)

        if status == "success":
            st.success("✅ シフトの作成に成功しました！")
            st.dataframe(df)

            summary_df = pd.DataFrame(index=df.index)
            summary_df['勤務日数'] = df.apply(lambda row: (row != '公休').sum(), axis=1)
            summary_df['当直回数'] = df.apply(lambda row: (row == '当直').sum(), axis=1)
            st.subheader("サマリー")
            st.dataframe(summary_df)

            csv = df.to_csv(index=True, encoding='utf-8-sig').encode('utf-8-sig')
            st.download_button(
                label="📄 CSVファイルをダウンロード",
                data=csv,
                file_name=f"shift_{year}_{month}.csv",
                mime="text/csv",
            )
        else:
            st.error("❌ シフトの作成に失敗しました。条件が厳しすぎる可能性があります（例：希望休と出勤希望が重複しているなど）。")
