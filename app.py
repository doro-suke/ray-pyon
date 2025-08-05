import streamlit as st
import pandas as pd
import jpholiday
from ortools.sat.python import cp_model
import calendar
from datetime import datetime
from streamlit_local_storage import LocalStorage

# --- シフト作成のコアロジック（関数として定義） ---
def create_shift_schedule(year, month, staff_names, holiday_requests, work_requests, nikkin_requirements, fixed_shifts):
    staff_count = len(staff_names)
    works = {"公休": 0, "日勤": 1, "半日": 2, "当直": 3, "明け": 4}
    work_symbols = {"公休": "ヤ", "日勤": "", "半日": "半", "当直": "△", "明け": "▲"}
    work_hours = {"公休": 0, "日勤": 8, "半日": 4, "当直": 16, "明け": 0}
    works_inv_symbols = {v: work_symbols[k] for k, v in works.items()}

    try:
        num_days = calendar.monthrange(year, month)[1]
    except calendar.IllegalMonthError:
        st.error("有効な月を入力してください（1-12）。")
        return None, None

    if num_days == 31:
        target_hours = 168
    else:
        target_hours = 160

    dates = [pd.Timestamp(f"{year}-{month}-{d}") for d in range(1, num_days + 1)]
    holidays = [d[0].day for d in jpholiday.month_holidays(year, month)]

    model = cp_model.CpModel()
    shifts = {}
    for s_idx in range(staff_count):
        for d_idx in range(num_days):
            shifts[(s_idx, d_idx)] = model.NewIntVar(0, len(works) - 1, f"shift_s{s_idx}_d{d_idx}")

    # --- 制約 ---
    for d_idx, date in enumerate(dates):
        is_on_duty = [model.NewBoolVar(f'd{d_idx}_s{s_idx}_is_duty') for s_idx in range(staff_count)]
        for s_idx in range(staff_count):
            model.Add(shifts[(s_idx, d_idx)] == works["当直"]).OnlyEnforceIf(is_on_duty[s_idx])
            model.Add(shifts[(s_idx, d_idx)] != works["当直"]).OnlyEnforceIf(is_on_duty[s_idx].Not())
        model.Add(sum(is_on_duty) == 1)
        
        is_holiday_or_sunday = (date.weekday() == 6) or (date.day in holidays)
        if is_holiday_or_sunday:
            for s_idx in range(staff_count):
                allowed_shifts = [works["当直"], works["明け"], works["公休"]]
                model.AddAllowedAssignments([shifts[(s_idx, d_idx)]], [(s,) for s in allowed_shifts])
        else:
            required_nikkin = nikkin_requirements[date.weekday()]
            if required_nikkin > 0:
                is_on_nikkin = [model.NewBoolVar(f'd{d_idx}_s{s_idx}_is_nikkin') for s_idx in range(staff_count)]
                for s_idx in range(staff_count):
                    model.Add(shifts[(s_idx, d_idx)] == works["日勤"]).OnlyEnforceIf(is_on_nikkin[s_idx])
                    model.Add(shifts[(s_idx, d_idx)] != works["日勤"]).OnlyEnforceIf(is_on_nikkin[s_idx].Not())
                model.Add(sum(is_on_nikkin) == required_nikkin)

    for s_idx in range(staff_count):
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
        work_symbol = fix['work']
        work_name = next((name for name, sym in work_symbols.items() if sym == work_symbol), None)
        if s_name in staff_names and work_name:
            s_idx = staff_names.index(s_name)
            d_idx = day - 1
            work_id = works.get(work_name)
            if work_id is not None:
                model.Add(shifts[(s_idx, d_idx)] == work_id)

    total_hours_per_staff = [model.NewIntVar(0, num_days * 16, f"total_hours_{s_idx}") for s_idx in range(staff_count)]
    hours_list = [0] * len(works)
    for name, id in works.items():
        hours_list[id] = work_hours.get(name, 0)
    for s_idx in range(staff_count):
        daily_hour_vars = [model.NewIntVar(0, 16, f's{s_idx}_d{d_idx}_hours') for d_idx in range(num_days)]
        for d_idx in range(num_days):
            model.AddElement(shifts[(s_idx, d_idx)], hours_list, daily_hour_vars[d_idx])
        model.Add(total_hours_per_staff[s_idx] == sum(daily_hour_vars))
    
    total_deviation = model.NewIntVar(0, staff_count * num_days * 16, 'total_deviation')
    abs_deviations = [model.NewIntVar(0, num_days * 16, f'abs_dev_{s_idx}') for s_idx in range(staff_count)]
    for s_idx in range(staff_count):
        deviation = model.NewIntVar(-num_days * 16, num_days * 16, f'dev_{s_idx}')
        model.Add(deviation == total_hours_per_staff[s_idx] - target_hours)
        model.AddAbsEquality(abs_deviations[s_idx], deviation)
    model.Add(total_deviation == sum(abs_deviations))

    duty_counts = [model.NewIntVar(0, num_days, f"duty_{s_idx}") for s_idx in range(staff_count)]
    for s_idx in range(staff_count):
        is_duty_bools = [model.NewBoolVar(f's{s_idx}_d{d_idx}_is_duty_count') for d_idx in range(num_days)]
        for d_idx in range(num_days):
            model.Add(shifts[(s_idx, d_idx)] == works["当直"]).OnlyEnforceIf(is_duty_bools[d_idx])
            model.Add(shifts[(s_idx, d_idx)] != works["当直"]).OnlyEnforceIf(is_duty_bools[d_idx].Not())
        model.Add(duty_counts[s_idx] == sum(is_duty_bools))
    
    min_duty, max_duty = model.NewIntVar(0, 10, 'min_d'), model.NewIntVar(0, 10, 'max_d')
    model.AddMinEquality(min_duty, duty_counts)
    model.AddMaxEquality(max_duty, duty_counts)
    duty_difference = model.NewIntVar(0, 10, 'duty_diff')
    model.Add(duty_difference == max_duty - min_duty)

    model.Minimize(total_deviation + (duty_difference * 10))

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = 30.0
    status = solver.Solve(model)

    if status == cp_model.OPTIMAL or status == cp_model.FEASIBLE:
        schedule = {}
        for s_idx, s_name in enumerate(staff_names):
            schedule[s_name] = [works_inv_symbols[solver.Value(shifts[(s_idx, d_idx)])] for d_idx in range(num_days)]
        df = pd.DataFrame(schedule).T
        return df, "success"
    else:
        return None, "failed"

# --- ここからがStreamlitのUI部分 ---
st.set_page_config(page_title="レイぴょん", layout="wide")
st.title("🏥 レイぴょん - シフト自動作成")

localS = LocalStorage()

def get_state(key, default_value):
    return localS.getItem(key) or default_value

st.header("1. 基本設定")
col1, col2, col3 = st.columns(3)
with col1:
    year = st.number_input("対象年", min_value=2024, max_value=2030, value=datetime.now().year)
with col2:
    month = st.number_input("対象月", min_value=1, max_value=12, value=datetime.now().month)
with col3:
    saved_staff_count = get_state('staff_count', 6)
    staff_count = st.number_input("スタッフ人数", min_value=1, max_value=20, value=int(saved_staff_count), key="staff_count")

st.header("2. スタッフの名前")
default_names = ["山田", "鈴木", "佐藤", "田中", "高橋", "渡辺", "伊藤", "山本", "中村", "小林",
                 "加藤", "吉田", "山口", "松本", "井上", "木村", "林", "佐々木", "清水", "山崎"]
staff_names = []
name_cols = st.columns(2)
for i in range(staff_count):
    with name_cols[i % 2]:
        saved_name = get_state(f'staff_name_{i}', default_names[i] if i < len(default_names) else f"スタッフ{i+1}")
        staff_names.append(st.text_input(f"スタッフ {i+1}の名前", value=saved_name, key=f"name_{i}"))

st.header("3. 曜日ごとの日勤人数")
weekdays = ["月", "火", "水", "木", "金", "土", "日"]
cols = st.columns(7)
nikkin_requirements = []
for i, day in enumerate(weekdays):
    with cols[i]:
        is_holiday_weekday = (i >= 5) # 土日の場合
        default_val = 1 if i == 4 else 0 if is_holiday_weekday else 2
        saved_nikkin_count = get_state(f'nikkin_{i}', default_val)
        
        if is_holiday_weekday:
            nikkin_requirements.append(st.number_input(day, min_value=0, max_value=0, value=0, key=f"nikkin_{i}", disabled=True, help="土日・祝日の日勤は0人に固定されています。"))
        else:
            nikkin_requirements.append(st.number_input(day, min_value=0, max_value=staff_count, value=int(saved_nikkin_count), key=f"nikkin_{i}"))
        
if saved_staff_count != staff_count:
    localS.setItem('staff_count', staff_count)
for i, name in enumerate(staff_names):
    saved_name = get_state(f'staff_name_{i}', default_names[i] if i < len(default_names) else f"スタッフ{i+1}")
    if saved_name != name:
        localS.setItem(f'staff_name_{i}', name)
for i in range(7):
    if i < 5: # 平日のみ保存
        default_val = 1 if i == 4 else 2
        saved_nikkin_count = get_state(f'nikkin_{i}', default_val)
        if saved_nikkin_count != nikkin_requirements[i]:
            localS.setItem(f'nikkin_{i}', nikkin_requirements[i])

st.header("4. スタッフごとの希望")
holiday_requests = {}
work_requests = {}
all_days = list(range(1, calendar.monthrange(year, month)[1] + 1))
num_columns = 3
cols = st.columns(num_columns)
for i, name in enumerate(staff_names):
    with cols[i % num_columns]:
        with st.expander(f"**{name}さんの希望**", expanded=True):
            holiday_requests[name] = st.multiselect("希望休", options=all_days, key=f"h_{i}")
            work_requests[name] = st.multiselect("出勤希望", options=all_days, key=f"w_{i}")

st.header("5. 特定の勤務を固定する（オプション）")
if 'fixed_shifts' not in st.session_state:
    st.session_state.fixed_shifts = []
col1, col2, col3, col4 = st.columns([2, 1, 1, 1])
with col1:
    fixed_name = st.selectbox("スタッフを選択", options=staff_names, key="fix_name", index=None, placeholder="名前を選択...")
with col2:
    fixed_day = st.selectbox("日付を選択", options=all_days, key="fix_day", index=None, placeholder="日を選択...")
with col3:
    fixed_work = st.selectbox("勤務を選択", options=["", "半", "△", "▲"], key="fix_work", index=None, placeholder="勤務を選択...")
with col4:
    st.write("") 
    st.write("")
    if st.button("追加", key="add_fix"):
        if fixed_name and fixed_day and fixed_work is not None:
            new_fix = {'staff': fixed_name, 'day': fixed_day, 'work': fixed_work}
            if new_fix not in st.session_state.fixed_shifts:
                st.session_state.fixed_shifts.append(new_fix)
        else:
            st.warning("スタッフ、日付、勤務をすべて選択してください。")
if st.session_state.fixed_shifts:
    st.write("---")
    st.write("現在固定されている勤務:")
    for i, fix in enumerate(st.session_state.fixed_shifts):
        display_work = "日勤" if fix['work'] == "" else fix['work']
        st.write(f"・ {fix['day']}日: **{fix['staff']}**さんを「**{display_work}**」に固定")
    if st.button("固定をすべてクリア", key="clear_fix"):
        st.session_state.fixed_shifts = []
        st.rerun()

st.header("6. シフト作成")
if 'schedule_df' not in st.session_state:
    st.session_state.schedule_df = None
if st.button("🚀 シフトを作成する", type="primary"):
    if len(staff_names) != len(set(staff_names)):
        st.error("エラー: スタッフの名前が重複しています。それぞれ違う名前にしてください。")
        st.session_state.schedule_df = None
    else:
        with st.spinner("最適なシフトを計算中です..."):
            df, status = create_shift_schedule(year, month, staff_names, holiday_requests, work_requests, nikkin_requirements, st.session_state.fixed_shifts)
        if status == "success":
            st.session_state.schedule_df = df
        else:
            st.session_state.schedule_df = None
            st.error("❌ シフトの作成に失敗しました。条件が厳しすぎる可能性があります。")

if st.session_state.schedule_df is not None:
    st.success("✅ シフトの作成に成功しました！")
    
    df_for_display = st.session_state.schedule_df.copy()
    
    weekdays_jp = ["月", "火", "水", "木", "金", "土", "日"]
    dates_for_header = [pd.Timestamp(f"{year}-{month}-{d}") for d in range(1, calendar.monthrange(year, month)[1] + 1)]
    
    header_tuples = []
    for date in dates_for_header:
        header_tuples.append((str(date.day), weekdays_jp[date.weekday()]))
    df_for_display.columns = pd.MultiIndex.from_tuples(header_tuples)

    # ▼▼▼【ここからが修正部分です】▼▼▼
    # 背景色を付けるスタイルを削除し、中央ぞろえのスタイルのみを適用
    styler = df_for_display.style.set_properties(**{'text-align': 'center'}).set_table_styles(
        [{'selector': 'th.col_heading', 'props': 'white-space: pre-wrap;'}]
    )
    # ▲▲▲ 修正完了 ▲▲▲
    
    st.dataframe(styler)
    
    st.subheader("サマリー")
    summary_df = pd.DataFrame(index=st.session_state.schedule_df.index)
    
    summary_work_hours = {"": 8, "半": 4, "△": 16, "▲": 0, "ヤ": 0}
    summary_df['総労働時間'] = st.session_state.schedule_df.apply(lambda row: sum(summary_work_hours.get(shift, 0) for shift in row), axis=1)
    summary_df['勤務日数'] = st.session_state.schedule_df.apply(lambda row: sum(1 for shift in row if shift != "ヤ"), axis=1)
    summary_df['当直回数'] = st.session_state.schedule_df.apply(lambda row: (row == '△').sum(), axis=1)
    st.dataframe(summary_df[['総労働時間', '勤務日数', '当直回数']])

    csv = st.session_state.schedule_df.to_csv(index=True, encoding='utf-8-sig').encode('utf-8-sig')
    st.download_button(
        label="📄 CSVファイルをダウンロード",
        data=csv,
        file_name=f"shift_{year}_{month}.csv",
        mime="text/csv",
    )
