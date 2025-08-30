import streamlit as st
import pandas as pd
import jpholiday
from ortools.sat.python import cp_model
import calendar
from datetime import datetime
from streamlit_local_storage import LocalStorage
from collections import defaultdict

# --- 定数定義 ---
# アプリケーション全体で共通のルールをスクリプトの先頭で定義します。
# これにより、設定の変更が容易になり、コードの保守性が向上します。
WORKS = {"公休": 0, "日勤": 1, "半日": 2, "当直": 3, "明け": 4}
WORK_SYMBOLS = {"公休": "ヤ", "日勤": "", "半日": "半", "当直": "△", "明け": "▲"}
WORK_HOURS = {"公休": 0, "日勤": 8, "半日": 4, "当直": 16, "明け": 0}

# 逆引き辞書もここで定義しておくと、コード内で何度も同じ変換処理を書かなくて済みます。
WORKS_INV_SYMBOLS = {v: WORK_SYMBOLS[k] for k, v in WORKS.items()}
SYMBOLS_INV_WORKS = {v: k for k, v in WORK_SYMBOLS.items()}

# --- 事前チェック機能 ---
def pre_check_constraints(staff_names, holiday_requests, work_requests, fixed_shifts):
    """ユーザー入力の矛盾を事前にチェックする"""
    for name in staff_names:
        holiday_set = set(holiday_requests.get(name, []))
        work_set = set(work_requests.get(name, []))
        if not holiday_set.isdisjoint(work_set):
            day = holiday_set.intersection(work_set).pop()
            return f"❌ **{name}さん**の希望休（{day}日）と出勤希望（{day}日）が重複しています。"

    for fix in fixed_shifts:
        name = fix['staff']
        day = fix['day']
        work_symbol = fix['work']
        display_work = "日勤" if work_symbol == "" else work_symbol

        if day in holiday_requests.get(name, []):
            return f"❌ **{name}さん**の固定シフト（{day}日：{display_work}）と希望休（{day}日）が重複しています。"
        
        work_name = SYMBOLS_INV_WORKS.get(work_symbol)
        if work_name == "公休" and day in work_requests.get(name, []):
            return f"❌ **{name}さん**の固定シフト（{day}日：公休）と出勤希望（{day}日）が重複しています。"

    fixed_duty_counts = defaultdict(int)
    for fix in fixed_shifts:
        if fix['work'] == WORK_SYMBOLS["当直"]:
            fixed_duty_counts[fix['day']] += 1
    
    for day, count in fixed_duty_counts.items():
        if count > 1:
            return f"❌ **{day}日**の当直に{count}人が固定されています。当直は1日1人までです。"
    
    return None

# --- シフト作成のコアロジック ---
def create_shift_schedule(year, month, staff_names, holiday_requests, work_requests, nikkin_requirements, fixed_shifts, max_half_days):
    staff_count = len(staff_names)

    try:
        num_days = calendar.monthrange(year, month)[1]
    except calendar.IllegalMonthError:
        st.error("有効な月を入力してください（1-12）。")
        return None, None

    target_hours = 168 if num_days == 31 else 160

    dates = [pd.Timestamp(f"{year}-{month}-{d}") for d in range(1, num_days + 1)]
    holidays_jp = [d[0].day for d in jpholiday.month_holidays(year, month)]

    model = cp_model.CpModel()
    shifts = {}
    for s_idx in range(staff_count):
        # ルール1: 公休の日数を8日～10日の範囲で変動させるように変更
        is_holiday_bools = [model.NewBoolVar(f's{s_idx}_d{d_idx}_is_holiday') for d_idx in range(num_days)]
        for d_idx in range(num_days):
            model.Add(shifts[(s_idx, d_idx)] == WORKS["公休"]).OnlyEnforceIf(is_holiday_bools[d_idx])
            model.Add(shifts[(s_idx, d_idx)] != WORKS["公休"]).OnlyEnforceIf(is_holiday_bools[d_idx].Not())
        model.AddLinearConstraint(sum(is_holiday_bools), 8, 10)

        # 総労働時間を計算する
        daily_hour_vars = [model.NewIntVar(0, 16, f's{s_idx}_d{d_idx}_hours') for d_idx in range(num_days)]
        for d_idx in range(num_days):
            model.AddElement(shifts[(s_idx, d_idx)], hours_list, daily_hour_vars[d_idx])
        model.Add(total_hours_per_staff[s_idx] == sum(daily_hour_vars))
        
        # ルール2: 総労働時間を目標±12時間の範囲に収める
        tolerance = 12
        model.Add(total_hours_per_staff[s_idx] >= target_hours - tolerance)
        model.Add(total_hours_per_staff[s_idx] <= target_hours + tolerance)

    # C7: 最適化目標 - 当直回数の公平化
    duty_counts = [model.NewIntVar(0, num_days, f"duty_{s_idx}") for s_idx in range(staff_count)]
    for s_idx in range(staff_count):
        is_duty_bools = [model.NewBoolVar(f's{s_idx}_d{d_idx}_is_duty_count') for d_idx in range(num_days)]
        for d_idx in range(num_days):
            # ▼▼▼【ここがエラー箇所です】誤った提案の .Leftrightarrow() を元の正しい記述に戻しました。▼▼▼
            model.Add(shifts[(s_idx, d_idx)] == WORKS["当直"]).OnlyEnforceIf(is_duty_bools[d_idx])
            model.Add(shifts[(s_idx, d_idx)] != WORKS["当直"]).OnlyEnforceIf(is_duty_bools[d_idx].Not())
        model.Add(duty_counts[s_idx] == sum(is_duty_bools))
    
    min_duty, max_duty = model.NewIntVar(0, 10, 'min_d'), model.NewIntVar(0, 10, 'max_d')
    model.AddMinEquality(min_duty, duty_counts)
    model.AddMaxEquality(max_duty, duty_counts)
    duty_difference = model.NewIntVar(0, 10, 'duty_diff')
    model.Add(duty_difference == max_duty - min_duty)

    model.Minimize(duty_difference)

    # --- ソルバーの実行 ---
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = 30.0
    status = solver.Solve(model)

    if status == cp_model.OPTIMAL or status == cp_model.FEASIBLE:
        schedule = {}
        for s_idx, s_name in enumerate(staff_names):
            schedule[s_name] = [WORKS_INV_SYMBOLS[solver.Value(shifts[(s_idx, d_idx)])] for d_idx in range(num_days)]
        df = pd.DataFrame(schedule).T
        return df, "success"
    else:
        return None, "failed"

# --- Streamlit UI ---
st.set_page_config(page_title="レイぴょん", layout="wide")
st.title("🏥 レイぴょん - シフト自動作成")

localS = LocalStorage()

def get_state(key, default_value):
    return localS.getItem(key) or default_value

def save_state(key, value):
    localS.setItem(key, value)

st.header("1. 基本設定")
col1, col2, col3 = st.columns(3)
with col1:
    year = st.number_input("対象年", min_value=2024, max_value=2030, value=datetime.now().year)
with col2:
    month = st.number_input("対象月", min_value=1, max_value=12, value=datetime.now().month)
with col3:
    saved_staff_count = get_state('staff_count', 6)
    staff_count = st.number_input(
        "スタッフ人数", min_value=1, max_value=20, value=int(saved_staff_count),
        key="staff_count_input",
        on_change=lambda: save_state('staff_count', st.session_state.staff_count_input)
    )

st.header("2. スタッフの名前")
default_names = ["山田", "鈴木", "佐藤", "田中", "高橋", "渡辺", "伊藤", "山本", "中村", "小林",
                 "加藤", "吉田", "山口", "松本", "井上", "木村", "林", "佐々木", "清水", "山崎"]
staff_names = []
name_cols = st.columns(2)
for i in range(staff_count):
    with name_cols[i % 2]:
        saved_name = get_state(f'staff_name_{i}', default_names[i] if i < len(default_names) else f"スタッフ{i+1}")
        staff_names.append(st.text_input(
            f"スタッフ {i+1}の名前", value=saved_name, key=f"name_{i}",
            on_change=lambda i=i: save_state(f'staff_name_{i}', st.session_state[f"name_{i}"])
        ))

st.header("3. 曜日ごとの日勤人数")
weekdays = ["月", "火", "水", "木", "金", "土", "日"]
cols = st.columns(7)
nikkin_requirements = []
for i, day in enumerate(weekdays):
    with cols[i]:
        default_val = 1 if i == 4 else 0 if i >= 5 else 2 # 金:1, 土日:0, その他:2
        saved_nikkin_count = get_state(f'nikkin_{i}', default_val)
        if i == 6: # 日曜日
            nikkin_requirements.append(st.number_input(day, min_value=0, max_value=0, value=0, key=f"nikkin_{i}", disabled=True, help="日曜・祝日の日勤は0人に固定されています。"))
        else:
            nikkin_requirements.append(st.number_input(
                day, min_value=0, max_value=staff_count, value=int(saved_nikkin_count), key=f"nikkin_{i}",
                on_change=lambda i=i: save_state(f'nikkin_{i}', st.session_state[f"nikkin_{i}"])
            ))

with st.expander("⚙️ 高度な設定"):
    max_half_days = st.slider(
        "各スタッフの半日勤務の上限回数",
        min_value=0, max_value=4, value=2,
        help="1人あたりの月間半日勤務の最大回数。労働時間を調整するために使われます。"
    )

st.header("4. スタッフごとの希望")
holiday_requests = {}
work_requests = {}
try:
    all_days = list(range(1, calendar.monthrange(year, month)[1] + 1))
except calendar.IllegalMonthError:
    all_days = []
    st.warning("月が不正です。1-12の範囲で入力してください。")

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
    fixed_work = st.selectbox("勤務を選択", options=WORK_SYMBOLS.values(), key="fix_work", index=None, placeholder="勤務を選択...")
with col4:
    st.write("") 
    st.write("")
    if st.button("追加", key="add_fix"):
        if fixed_name and fixed_day and fixed_work is not None:
            new_fix = {'staff': fixed_name, 'day': fixed_day, 'work': fixed_work}
            if new_fix not in st.session_state.fixed_shifts:
                st.session_state.fixed_shifts.append(new_fix)
                st.rerun()
        else:
            st.warning("スタッフ、日付、勤務をすべて選択してください。")

if st.session_state.fixed_shifts:
    st.write("---")
    st.write("現在固定されている勤務:")
    for i, fix in enumerate(st.session_state.fixed_shifts):
        display_work = SYMBOLS_INV_WORKS.get(fix['work'], "不明")
        st.write(f"・ {fix['day']}日: **{fix['staff']}**さんを「**{display_work}**」に固定")
    if st.button("固定をすべてクリア", key="clear_fix"):
        st.session_state.fixed_shifts = []
        st.rerun()

st.header("6. シフト作成")
if 'schedule_df' not in st.session_state:
    st.session_state.schedule_df = None

if st.button("🚀 シフトを作成する", type="primary"):
    error_message = pre_check_constraints(staff_names, holiday_requests, work_requests, st.session_state.fixed_shifts)
    if error_message:
        st.error(error_message)
        st.session_state.schedule_df = None
    elif len(staff_names) != len(set(staff_names)):
        st.error("エラー: スタッフの名前が重複しています。それぞれ違う名前にしてください。")
        st.session_state.schedule_df = None
    else:
        with st.spinner("最適なシフトを計算中です..."):
            df, status = create_shift_schedule(year, month, staff_names, holiday_requests, work_requests, nikkin_requirements, st.session_state.fixed_shifts, max_half_days)
        if status == "success":
            st.session_state.schedule_df = df
        else:
            st.session_state.schedule_df = None
            st.error("❌ シフトの作成に失敗しました。条件が複雑で解決できない可能性があります（例：希望休が多すぎるなど）。")

if st.session_state.schedule_df is not None:
    st.success("✅ シフトの作成に成功しました！")
    
    df_for_display = st.session_state.schedule_df.copy()
    
    weekdays_jp = ["月", "火", "水", "木", "金", "土", "日"]
    num_days_in_month = calendar.monthrange(year, month)[1]
    dates_for_header = [pd.Timestamp(f"{year}-{month}-{d}") for d in range(1, num_days_in_month + 1)]
    
    header_tuples = []
    for date in dates_for_header:
        header_tuples.append((str(date.day), weekdays_jp[date.weekday()]))
    df_for_display.columns = pd.MultiIndex.from_tuples(header_tuples)

    styler = df_for_display.style.set_properties(**{'text-align': 'center'}).set_table_styles([
        {'selector': 'th.col_heading', 'props': [
            ('white-space', 'pre-wrap;'),
            ('text-align', 'center')
        ]},
        {'selector': 'th.row_heading', 'props': [('text-align', 'center')]}
    ])
    st.dataframe(styler)
    
    st.subheader("サマリー")
    summary_df = pd.DataFrame(index=st.session_state.schedule_df.index)
    
    summary_work_hours = {sym: WORK_HOURS[name] for sym, name in SYMBOLS_INV_WORKS.items()}
    summary_df['総労働時間'] = st.session_state.schedule_df.apply(lambda row: sum(summary_work_hours.get(shift, 0) for shift in row), axis=1)
    summary_df['勤務日数'] = st.session_state.schedule_df.apply(lambda row: sum(1 for shift in row if shift != WORK_SYMBOLS["公休"]), axis=1)
    summary_df['公休数'] = st.session_state.schedule_df.apply(lambda row: (row == WORK_SYMBOLS["公休"]).sum(), axis=1)
    summary_df['半日数'] = st.session_state.schedule_df.apply(lambda row: (row == WORK_SYMBOLS["半日"]).sum(), axis=1)
    summary_df['当直回数'] = st.session_state.schedule_df.apply(lambda row: (row == WORK_SYMBOLS["当直"]).sum(), axis=1)
    st.dataframe(summary_df[['総労働時間', '勤務日数', '公休数', '半日数', '当直回数']])

    csv_df = st.session_state.schedule_df.copy()
    new_columns_for_csv = [f"{day_tuple[0]} {day_tuple[1]}" for day_tuple in header_tuples]
    csv_df.columns = new_columns_for_csv
    
    csv = csv_df.to_csv(index=True, encoding='utf-8-sig').encode('utf-8-sig')
    st.download_button(
        label="📄 CSVファイルをダウンロード",
        data=csv,
        file_name=f"shift_{year}_{month}.csv",
        mime="text/csv",
    )

