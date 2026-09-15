# -*- coding: utf-8 -*-
"""
WBC 스크린야구 기록 관리 시스템 - Flask 메인 애플리케이션
세계로교회 World Believers Club
"""
from flask import (Flask, render_template, request, jsonify,
                   redirect, url_for, send_file, flash, session)
import sys, os, io, sqlite3, json
from datetime import date, datetime
from functools import wraps
try:
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')
except Exception:
    pass

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'wbc-screen-baseball-secret-2026')
app.config['TEMPLATES_AUTO_RELOAD'] = True
app.config['SEND_FILE_MAX_AGE_DEFAULT'] = 0
DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'wbc_data.db')

# 운영진 마스터 비밀번호 (교회 전화번호 뒷자리 7500, 환경변수 ADMIN_PASSWORD로 변경 가능)
ADMIN_PASSWORD = os.environ.get('ADMIN_PASSWORD', '7500')

# ─────────────────────────────────────────────
# 운영진 인증 헬퍼 및 컨텍스트
# ─────────────────────────────────────────────
def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get('is_admin'):
            if request.is_json or request.path.startswith('/api/'):
                return jsonify({'ok': False, 'err': '운영진 권한이 필요합니다. 먼저 로그인해주세요.'}), 401
            flash('🔒 운영진 권한이 필요한 기능입니다. 비밀번호를 입력해주세요.', 'warning')
            return redirect(url_for('login_page', next=request.url))
        return f(*args, **kwargs)
    return decorated_function

# 야구 표준 타율/장타율/출루율 포맷팅 (1.000 이상은 1.000 / 1.500 / 2.000 등 정수부 보존, 1미만은 .333 표기)
def fmt_rate(val):
    if val is None:
        return ".000"
    try:
        v = float(val)
    except (ValueError, TypeError):
        return ".000"
    if v >= 1.0:
        return f"{v:.3f}"
    s = f"{v:.3f}"
    if s.startswith('0.'):
        return s[1:]
    return s

@app.template_filter('rate')
def rate_filter(val):
    return fmt_rate(val)

@app.context_processor
def inject_auth():
    return {
        'is_admin': session.get('is_admin', False),
        'fmt_rate': fmt_rate
    }

# ─────────────────────────────────────────────
# DB 헬퍼 (WAL 모드 & Busy Timeout 동시성 강화)
# ─────────────────────────────────────────────
def get_db():
    conn = sqlite3.connect(DB_PATH, timeout=10.0)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA foreign_keys = ON')
    conn.execute('PRAGMA journal_mode = WAL')
    conn.execute('PRAGMA busy_timeout = 5000')
    return conn

def init_db():
    conn = get_db()
    c = conn.cursor()
    c.executescript('''
        CREATE TABLE IF NOT EXISTS players (
            id        INTEGER PRIMARY KEY AUTOINCREMENT,
            name      TEXT NOT NULL,
            team      TEXT NOT NULL,
            is_active INTEGER DEFAULT 1,
            created_at TEXT DEFAULT (datetime('now','localtime'))
        );
        CREATE TABLE IF NOT EXISTS games (
            id               INTEGER PRIMARY KEY AUTOINCREMENT,
            game_date        TEXT NOT NULL,
            game_number      INTEGER,
            location         TEXT DEFAULT '스크린야구장',
            world_score      INTEGER,
            believers_score  INTEGER,
            notes            TEXT,
            created_at       TEXT DEFAULT (datetime('now','localtime'))
        );
        CREATE TABLE IF NOT EXISTS batting_records (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            game_id     INTEGER NOT NULL,
            player_id   INTEGER NOT NULL,
            team        TEXT NOT NULL,
            batting_order INTEGER DEFAULT 0,
            inn1  TEXT, inn2  TEXT, inn3  TEXT, inn4  TEXT, inn5  TEXT,
            inn6  TEXT, inn7  TEXT, inn8  TEXT, inn9  TEXT,
            inn10 TEXT, inn11 TEXT, inn12 TEXT, inn13 TEXT,
            ab        INTEGER DEFAULT 0,
            hits      INTEGER DEFAULT 0,
            singles   INTEGER DEFAULT 0,
            doubles   INTEGER DEFAULT 0,
            triples   INTEGER DEFAULT 0,
            hr        INTEGER DEFAULT 0,
            rbi       INTEGER DEFAULT 0,
            bb        INTEGER DEFAULT 0,
            k         INTEGER DEFAULT 0,
            out_count INTEGER DEFAULT 0,
            dp        INTEGER DEFAULT 0,
            avg REAL DEFAULT 0.0,
            slg REAL DEFAULT 0.0,
            obp REAL DEFAULT 0.0,
            FOREIGN KEY (game_id)   REFERENCES games(id)   ON DELETE CASCADE,
            FOREIGN KEY (player_id) REFERENCES players(id)
        );
    ''')
    cnt = c.execute('SELECT COUNT(*) FROM players').fetchone()[0]
    if cnt == 0:
        seed = [
            ('김진혁','World'),('김응관','World'),('이주호','World'),
            ('배석원','World'),('황주현','World'),('이성수','World'),
            ('김신광','Believers'),('김석희','Believers'),('박동진','Believers'),
            ('임명길','Believers'),('정재홍','Believers'),('이승원','Believers'),
            ('서관승','Believers'),('이종욱','Believers'),
        ]
        c.executemany('INSERT INTO players(name,team) VALUES(?,?)', seed)
    
    # Check if match_type and score_details columns exist in games
    cols = [col[1] for col in c.execute("PRAGMA table_info(games)").fetchall()]
    if 'match_type' not in cols:
        c.execute("ALTER TABLE games ADD COLUMN match_type TEXT DEFAULT '2teams'")
    if 'score_details' not in cols:
        c.execute("ALTER TABLE games ADD COLUMN score_details TEXT DEFAULT ''")

    conn.commit()
    conn.close()

# ─────────────────────────────────────────────
# 기호 파싱 / 통계 계산
# ─────────────────────────────────────────────
def parse_sym(s):
    if s is None: s = ''
    s = str(s).strip()
    if s in ('','-'): return dict(ab=0,hits=0,singles=0,doubles=0,triples=0,hr=0,k=0,out=0,dp=0)
    if s == '1':  return dict(ab=1,hits=1,singles=1,doubles=0,triples=0,hr=0,k=0,out=0,dp=0)
    if s == '2':  return dict(ab=1,hits=1,singles=0,doubles=1,triples=0,hr=0,k=0,out=0,dp=0)
    if s == '3':  return dict(ab=1,hits=1,singles=0,doubles=0,triples=1,hr=0,k=0,out=0,dp=0)
    if s in ('★','HR','4'): return dict(ab=1,hits=1,singles=0,doubles=0,triples=0,hr=1,k=0,out=0,dp=0)
    if s == 'K':  return dict(ab=1,hits=0,singles=0,doubles=0,triples=0,hr=0,k=1,out=0,dp=0)
    if s == 'O':  return dict(ab=1,hits=0,singles=0,doubles=0,triples=0,hr=0,k=0,out=1,dp=0)
    if s == 'DP': return dict(ab=1,hits=0,singles=0,doubles=0,triples=0,hr=0,k=0,out=0,dp=1)
    return dict(ab=0,hits=0,singles=0,doubles=0,triples=0,hr=0,k=0,out=0,dp=0)

def calc_stats(innings):
    t = dict(ab=0,hits=0,singles=0,doubles=0,triples=0,hr=0,k=0,out=0,dp=0)
    for sym in innings:
        p = parse_sym(sym)
        for k in t: t[k] += p[k]
    ab = t['ab']
    t['avg'] = round(t['hits']/ab,3) if ab>0 else 0.0
    slg_tb  = t['singles']+t['doubles']*2+t['triples']*3+t['hr']*4
    t['slg'] = round(slg_tb/ab,3) if ab>0 else 0.0
    t['obp'] = t['avg']
    return t

def fmt_date(d):
    try:
        dt = datetime.strptime(str(d),'%Y-%m-%d')
        return f"{dt.year}년 {dt.month:02d}월 {dt.day:02d}일"
    except:
        return str(d)

# ─────────────────────────────────────────────
# 운영진 인증 라우트
# ─────────────────────────────────────────────
@app.route('/login', methods=['GET', 'POST'])
def login_page():
    next_url = request.args.get('next') or request.form.get('next') or url_for('index')
    if request.method == 'POST':
        pw = request.form.get('password', '').strip()
        if pw == ADMIN_PASSWORD:
            session['is_admin'] = True
            flash('🔓 운영진 모드로 로그인되었습니다.', 'success')
            return redirect(next_url)
        else:
            flash('❌ 비밀번호가 올바르지 않습니다. 다시 확인해주세요.', 'danger')
            return render_template('login.html', next=next_url)
    return render_template('login.html', next=next_url)

@app.route('/api/login', methods=['POST'])
def api_login():
    data = request.get_json() or {}
    pw = str(data.get('password', '')).strip()
    if pw == ADMIN_PASSWORD:
        session['is_admin'] = True
        return jsonify({'ok': True, 'msg': '로그인 성공'})
    return jsonify({'ok': False, 'err': '비밀번호가 올바르지 않습니다.'}), 401

@app.route('/logout', methods=['GET', 'POST'])
def logout():
    session.pop('is_admin', None)
    flash('🔒 로그아웃되었습니다. 일반 열람 모드로 전환됩니다.', 'info')
    return redirect(request.referrer or url_for('index'))

# ─────────────────────────────────────────────
# 전광판(Scoreboard) 데이터 파싱 헬퍼
# ─────────────────────────────────────────────
def get_scoreboard_data(game, conn=None):
    if not game:
        return None
    details = {}
    if game['score_details']:
        try:
            details = json.loads(game['score_details'])
        except Exception:
            details = {}
    
    if details.get('teams') and isinstance(details['teams'], list):
        return details
    
    gid = game['id']
    close_conn = False
    if conn is None:
        conn = get_db()
        close_conn = True
        
    t_stats = conn.execute('''
        SELECT team, SUM(ab) tab, SUM(hits) thits, SUM(hr) thr, SUM(rbi) trbi
        FROM batting_records WHERE game_id = ?
        GROUP BY team
    ''', (gid,)).fetchall()
    
    stat_map = {row['team']: dict(row) for row in t_stats}
    if close_conn:
        conn.close()
        
    w_score = game['world_score'] if game['world_score'] is not None else 0
    b_score = game['believers_score'] if game['believers_score'] is not None else 0
    
    teams = [
        {
            'name': 'World',
            'team_name': 'World ⚡',
            'badge_class': 'badge-world',
            'order': 'top',
            'order_label': '초 (선공)',
            'scores': ['-'] * 9,
            'r': w_score,
            'h': stat_map.get('World', {}).get('thits', 0),
            'e': 0,
            'hr': stat_map.get('World', {}).get('thr', 0),
            'is_winner': w_score > b_score
        },
        {
            'name': 'Believers',
            'team_name': 'Believers 🔥',
            'badge_class': 'badge-believers',
            'order': 'bottom',
            'order_label': '말 (후공)',
            'scores': ['-'] * 9,
            'r': b_score,
            'h': stat_map.get('Believers', {}).get('thits', 0),
            'e': 0,
            'hr': stat_map.get('Believers', {}).get('thr', 0),
            'is_winner': b_score > w_score
        }
    ]
    return {
        'innings_count': 9,
        'start_inning': 1,
        'played_innings': 9,
        'note': '정규 경기',
        'teams': teams
    }

# ─────────────────────────────────────────────
# 라우트
# ─────────────────────────────────────────────
@app.route('/')
def index():
    conn = get_db()
    latest = conn.execute(
        'SELECT * FROM games ORDER BY game_date DESC, id DESC LIMIT 1'
    ).fetchone()
    game_count = conn.execute('SELECT COUNT(*) FROM games').fetchone()[0]
    total_players = conn.execute('SELECT COUNT(*) FROM players WHERE is_active = 1').fetchone()[0]

    # 시즌 종합 통계
    season_row = conn.execute('''
        SELECT COALESCE(SUM(ab), 0) tab,
               COALESCE(SUM(hits), 0) th,
               COALESCE(SUM(hr), 0) thr,
               COALESCE(SUM(rbi), 0) trbi
        FROM batting_records
    ''').fetchone()
    season_hits = season_row['th']
    season_hr = season_row['thr']
    season_rbi = season_row['trbi']
    season_avg = round(season_row['th'] / season_row['tab'], 3) if season_row['tab'] > 0 else 0.0

    # TOP 5 선수 (p.id 포함)
    top5 = conn.execute('''
        SELECT p.id, p.name, p.team,
               COUNT(DISTINCT br.game_id) games,
               SUM(br.ab) tab, SUM(br.hits) th, SUM(br.hr) thr, SUM(br.rbi) trbi,
               CASE WHEN SUM(br.ab)>0
                    THEN ROUND(CAST(SUM(br.hits) AS REAL)/SUM(br.ab),3)
                    ELSE 0 END savg,
               CASE WHEN SUM(br.ab)>0
                    THEN ROUND(CAST(SUM(br.singles)+SUM(br.doubles)*2+SUM(br.triples)*3+SUM(br.hr)*4 AS REAL)/SUM(br.ab),3)
                    ELSE 0 END sslg
        FROM batting_records br JOIN players p ON p.id=br.player_id
        GROUP BY p.id HAVING SUM(br.ab)>=1
        ORDER BY savg DESC, th DESC LIMIT 5
    ''').fetchall()

    latest_recs = []
    latest_team_stats = {}
    latest_awards = {}
    scoreboard = None
    if latest:
        gid = latest['id']
        scoreboard = get_scoreboard_data(latest, conn)
        latest_recs = conn.execute('''
            SELECT p.name,p.team,br.ab,br.hits,br.hr,br.avg,br.slg,br.batting_order
            FROM batting_records br JOIN players p ON p.id=br.player_id
            WHERE br.game_id=? ORDER BY br.team, br.batting_order
        ''', (gid,)).fetchall()

        t_stats = conn.execute('''
            SELECT team, SUM(ab) tab, SUM(hits) thits, SUM(hr) thr, SUM(rbi) trbi
            FROM batting_records WHERE game_id = ?
            GROUP BY team
        ''', (gid,)).fetchall()
        for row in t_stats:
            latest_team_stats[row['team']] = dict(row)

        latest_awards = calc_game_awards(gid)

    conn.close()
    return render_template('index.html',
        latest=latest, game_count=game_count, total_players=total_players,
        season_hits=season_hits, season_hr=season_hr, season_rbi=season_rbi, season_avg=season_avg,
        top5=top5, latest_recs=latest_recs, latest_team_stats=latest_team_stats,
        latest_awards=latest_awards, scoreboard=scoreboard, fmt_date=fmt_date)

@app.route('/game/new')
@admin_required
def game_new():
    conn = get_db()
    players = conn.execute(
        'SELECT * FROM players WHERE is_active=1 ORDER BY team, id'
    ).fetchall()
    game_count = conn.execute('SELECT COUNT(*) FROM games').fetchone()[0]
    conn.close()
    return render_template('game_input.html',
        players=players, today=date.today().isoformat(),
        next_num=game_count+1, edit_game=None, edit_records=[])

@app.route('/game/<int:gid>/edit')
@admin_required
def game_edit(gid):
    conn = get_db()
    game = conn.execute('SELECT * FROM games WHERE id=?', (gid,)).fetchone()
    if not game:
        conn.close()
        flash('수정할 경기 정보를 찾을 수 없습니다.', 'danger')
        return redirect(url_for('history'))
    
    players = conn.execute(
        'SELECT * FROM players WHERE is_active=1 ORDER BY team, id'
    ).fetchall()
    recs = conn.execute('''
        SELECT p.name, p.team, br.*
        FROM batting_records br JOIN players p ON p.id=br.player_id
        WHERE br.game_id=? ORDER BY br.team, br.batting_order
    ''', (gid,)).fetchall()
    conn.close()

    return render_template('game_input.html',
        players=players, today=game['game_date'],
        next_num=game['game_number'],
        edit_game=dict(game),
        edit_records=[dict(r) for r in recs])

@app.route('/game/save', methods=['POST'])
@admin_required
def game_save():
    data = request.get_json()
    if not data:
        return jsonify({'ok':False,'err':'데이터 없음'}), 400
    conn = get_db()
    try:
        c = conn.cursor()
        edit_gid = data.get('edit_game_id')
        match_type = data.get('match_type', '2teams')
        score_details = data.get('score_details', '')

        if edit_gid:
            gid = int(edit_gid)
            c.execute('''UPDATE games 
                         SET game_date=?, game_number=?, location=?, world_score=?, believers_score=?, notes=?, match_type=?, score_details=?
                         WHERE id=?''',
                (data.get('game_date'), data.get('game_number'),
                 data.get('location','스크린야구장'),
                 data.get('world_score'), data.get('believers_score'),
                 data.get('notes',''), match_type, score_details, gid))
            c.execute('DELETE FROM batting_records WHERE game_id=?', (gid,))
        else:
            c.execute('''INSERT INTO games(game_date,game_number,location,world_score,believers_score,notes,match_type,score_details)
                         VALUES(?,?,?,?,?,?,?,?)''',
                (data.get('game_date'), data.get('game_number'),
                 data.get('location','스크린야구장'),
                 data.get('world_score'), data.get('believers_score'),
                 data.get('notes',''), match_type, score_details))
            gid = c.lastrowid

        for rec in data.get('records',[]):
            pid = rec.get('player_id')
            pname = str(rec.get('name') or '').strip()
            if not pname and not pid:
                continue
            
            # Auto-register if new player on the fly (substitute, guest)
            if not pid or pid == 0 or str(pid) == '0':
                if not pname:
                    continue
                c.execute('SELECT id FROM players WHERE name = ?', (pname,))
                found = c.fetchone()
                if found:
                    pid = found[0]
                else:
                    c.execute('INSERT INTO players (name, team) VALUES (?, ?)', (pname, rec.get('team', 'World')))
                    pid = c.lastrowid

            innings = [rec.get(f'inn{i}') for i in range(1,14)]
            st = calc_stats(innings)
            c.execute('''INSERT INTO batting_records
                (game_id,player_id,team,batting_order,
                 inn1,inn2,inn3,inn4,inn5,inn6,inn7,inn8,inn9,inn10,inn11,inn12,inn13,
                 ab,hits,singles,doubles,triples,hr,rbi,bb,k,out_count,dp,avg,slg,obp)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
                (gid, pid, rec['team'], rec.get('order',0),
                 *innings,
                 st['ab'],st['hits'],st['singles'],st['doubles'],st['triples'],st['hr'],
                 rec.get('rbi',0), rec.get('bb',0),
                 st['k'],st['out'],st['dp'],st['avg'],st['slg'],st['obp']))
        conn.commit()
        return jsonify({'ok':True,'game_id':gid})
    except Exception as e:
        conn.rollback()
        return jsonify({'ok':False,'err':str(e)}), 500
    finally:
        conn.close()

@app.route('/game/<int:gid>')
def game_detail(gid):
    conn = get_db()
    game = conn.execute('SELECT * FROM games WHERE id=?',(gid,)).fetchone()
    if not game: return redirect(url_for('history'))
    scoreboard = get_scoreboard_data(game, conn)
    recs = conn.execute('''
        SELECT p.name,p.team,br.*
        FROM batting_records br JOIN players p ON p.id=br.player_id
        WHERE br.game_id=? ORDER BY br.team,br.batting_order
    ''',(gid,)).fetchall()
    conn.close()
    awards = calc_game_awards(gid)
    return render_template('game_detail.html', game=game, records=recs, awards=awards, scoreboard=scoreboard, fmt_date=fmt_date)

@app.route('/game/<int:gid>/delete', methods=['POST'])
@admin_required
def game_delete(gid):
    conn = get_db()
    conn.execute('DELETE FROM games WHERE id=?',(gid,))
    conn.commit(); conn.close()
    flash('경기 기록이 삭제되었습니다.','success')
    return redirect(url_for('history'))

@app.route('/rankings')
def rankings():
    team = request.args.get('team','all')
    where = 'AND p.team=?' if team != 'all' else ''
    params = [team] if team != 'all' else []
    conn = get_db()
    rows = conn.execute(f'''
        SELECT p.id,p.name,p.team,
               COUNT(DISTINCT br.game_id) games,
               SUM(br.ab) tab, SUM(br.hits) th,
               SUM(br.singles) t1b, SUM(br.doubles) t2b, SUM(br.triples) t3b,
               SUM(br.hr) thr, SUM(br.rbi) trbi, SUM(br.k) tk, SUM(br.dp) tdp,
               CASE WHEN SUM(br.ab)>0
                    THEN ROUND(CAST(SUM(br.hits) AS REAL)/SUM(br.ab),3) ELSE 0 END savg,
               CASE WHEN SUM(br.ab)>0
                    THEN ROUND(CAST(SUM(br.singles)+SUM(br.doubles)*2+SUM(br.triples)*3+SUM(br.hr)*4 AS REAL)/SUM(br.ab),3) ELSE 0 END sslg,
               CASE WHEN SUM(br.ab)>0
                    THEN ROUND(CAST(SUM(br.hits) AS REAL)/SUM(br.ab),3) ELSE 0 END sobp,
               MAX(br.game_id) last_game_id
        FROM players p
        LEFT JOIN batting_records br ON br.player_id=p.id
        WHERE p.is_active=1 {where}
        GROUP BY p.id HAVING SUM(br.ab)>=1
        ORDER BY savg DESC, th DESC, tab DESC
    ''', params).fetchall()
    conn.close()
    return render_template('rankings.html', players=rows, team_filter=team)

@app.route('/history')
def history():
    conn = get_db()
    games = conn.execute('''
        SELECT g.*,
               COUNT(DISTINCT CASE WHEN br.team='World' THEN br.player_id END) w_players,
               COUNT(DISTINCT CASE WHEN br.team='Believers' THEN br.player_id END) b_players,
               SUM(br.hits) total_hits, SUM(br.hr) total_hr
        FROM games g LEFT JOIN batting_records br ON br.game_id=g.id
        GROUP BY g.id ORDER BY g.game_date DESC, g.id DESC
    ''').fetchall()
    conn.close()
    return render_template('history.html', games=games, fmt_date=fmt_date)

def calc_mvp_points(r):
    """
    [WBC 공인 경기 MVP 종합 활약도 점수 산정 공식]
    1. 타점 (득점 직접 기여 / 해결사 능력): +3.0점 (가장 중요)
    2. 홈런 (장타 & 득점): +3.5점
    3. 3루타: +2.5점
    4. 2루타: +1.8점
    5. 1루타(단타): +1.0점
    6. 타율 보너스 (안타 생산율): (타율 * 2.0)점
    7. 삼진(아웃 기여 감점): -0.5점
    8. 병살타(찬스 무산 감점): -1.0점
    """
    if not r or r['ab'] <= 0:
        return 0.0
    
    singles = r['singles'] if 'singles' in r.keys() else max(0, r['hits'] - (r['doubles'] or 0) - (r['triples'] or 0) - (r['hr'] or 0))
    doubles = r['doubles'] or 0
    triples = r['triples'] or 0
    hr = r['hr'] or 0
    rbi = r['rbi'] or 0
    avg = r['avg'] or 0.0
    k = r['k'] if 'k' in r.keys() else 0
    dp = r['dp'] if 'dp' in r.keys() else 0

    pts = (rbi * 3.0) + (hr * 3.5) + (triples * 2.5) + (doubles * 1.8) + (singles * 1.0) + (avg * 2.0) - (k * 0.5) - (dp * 1.0)
    return round(max(0.0, pts), 1)

def calc_game_awards(gid):
    """
    [WBC 경기별 명예의 전당 / 특별 시상 체계]
    1. 🏅 MVP (최우수 선수): 가중치 종합점수 1위
    2. ✨ MIP (Most Improved Player / 기량 발전상):
       - 이전 경기 누적 타율 대비 이번 경기 타율 상승 폭(+Δ)이 가장 큰 성장 선수
       - 단일 경기인 경우 비-MVP 중 최고 타율/출루 선수
    3. 🛡️ 언성 히어로 (Unsung Hero / 보이지 않는 영웅상):
       - 4번 타순 이상 하위 타선에서 묵묵히 득점과 찬스를 만든 알짜배기 비-MVP 선수
    4. 🔥 허슬 플레이어 (Hustle Player / 열정 투혼상):
       - 삼진 0개 및 최다 타석으로 끈질기게 인플레이를 만들어낸 투혼의 선수
    """
    conn = get_db()
    game = conn.execute('SELECT * FROM games WHERE id=?', (gid,)).fetchone()
    if not game:
        conn.close()
        return {}

    recs = conn.execute('''
        SELECT p.id as player_id, p.name, p.team,
               br.batting_order, br.ab, br.hits, br.singles, br.doubles,
               br.triples, br.hr, br.rbi, br.k, br.dp, br.avg, br.slg
        FROM batting_records br
        JOIN players p ON p.id = br.player_id
        WHERE br.game_id = ?
    ''', (gid,)).fetchall()

    rec_list = []
    for r in recs:
        rd = dict(r)
        rd['mvp_pts'] = calc_mvp_points(r)
        rec_list.append(rd)

    if not rec_list:
        conn.close()
        return {}

    # 1. MVP: 최고 활약점수 1위
    sorted_mvp = sorted([r for r in rec_list if r['ab'] > 0], key=lambda x: x['mvp_pts'], reverse=True)
    mvp = sorted_mvp[0] if sorted_mvp else None

    # 2. MIP (Most Improved Player / 기량 발전상)
    prior_games = conn.execute('''
        SELECT id FROM games 
        WHERE game_date < ? OR (game_date = ? AND id < ?)
        ORDER BY game_date ASC, id ASC
    ''', (game['game_date'], game['game_date'], gid)).fetchall()

    mip = None
    mip_reason = ""
    if prior_games:
        prior_gids = [g['id'] for g in prior_games]
        placeholders = ','.join('?' * len(prior_gids))
        prior_stats = conn.execute(f'''
            SELECT player_id, SUM(ab) pab, SUM(hits) phits
            FROM batting_records
            WHERE game_id IN ({placeholders})
            GROUP BY player_id
        ''', prior_gids).fetchall()
        p_dict = {p['player_id']: (p['phits'] / p['pab'] if p['pab'] > 0 else 0.0) for p in prior_stats}

        improvement_list = []
        for r in rec_list:
            if r['ab'] >= 2 and (not mvp or r['player_id'] != mvp['player_id']):
                p_avg = p_dict.get(r['player_id'], 0.0)
                diff = r['avg'] - p_avg
                improvement_list.append((diff, r, p_avg))
        if improvement_list:
            improvement_list.sort(key=lambda x: x[0], reverse=True)
            best_diff, best_r, p_avg = improvement_list[0]
            if best_diff > 0:
                mip = best_r
                mip_reason = f"이전 누적 대비 타율 +{best_diff:.3f} 대폭 상승! ({p_avg:.3f} → {best_r['avg']:.3f})"

    if not mip:
        non_mvp_cands = [r for r in rec_list if (not mvp or r['player_id'] != mvp['player_id']) and r['hits'] >= 1]
        if non_mvp_cands:
            non_mvp_cands.sort(key=lambda x: (x['avg'], x['hits']), reverse=True)
            mip = non_mvp_cands[0]
            mip_reason = f"놀라운 집중력과 정교한 타격 ({mip['ab']}타수 {mip['hits']}안타, 타율 {mip['avg']:.3f})"

    # 3. 언성 히어로 (Unsung Hero / 보이지 않는 영웅상)
    unsung_cands = [
        r for r in rec_list 
        if (r['batting_order'] or 1) >= 4 
        and (not mvp or r['player_id'] != mvp['player_id'])
        and (not mip or r['player_id'] != mip['player_id'])
        and (r['hits'] >= 1 or r['rbi'] >= 1)
    ]
    unsung = None
    unsung_reason = ""
    if unsung_cands:
        unsung_cands.sort(key=lambda x: (x['mvp_pts'], x['rbi'], x['hits']), reverse=True)
        unsung = unsung_cands[0]
        unsung_reason = f"하위 타선({unsung['batting_order']}번 타순) 알짜배기 활약 ({unsung['ab']}타수 {unsung['hits']}안타 {unsung['rbi']}타점)"
    else:
        remain = [r for r in sorted_mvp if (not mvp or r['player_id'] != mvp['player_id']) and (not mip or r['player_id'] != mip['player_id'])]
        if remain:
            unsung = remain[0]
            unsung_reason = f"팀을 위한 묵묵한 공헌 ({unsung['ab']}타수 {unsung['hits']}안타)"

    # 4. 허슬 플레이어 (Hustle Player / 열정 투혼상)
    hustle_cands = [
        r for r in rec_list
        if r['ab'] >= 3 and r['k'] == 0
        and (not mvp or r['player_id'] != mvp['player_id'])
    ]
    hustle = None
    hustle_reason = ""
    if hustle_cands:
        hustle_cands.sort(key=lambda x: (x['ab'], x['hits']), reverse=True)
        hustle = hustle_cands[0]
        hustle_reason = f"{hustle['ab']}타수 삼진 0개! 끈질긴 인플레이와 전력 배팅"

    conn.close()
    return {
        'mvp': mvp,
        'mip': mip,
        'mip_reason': mip_reason,
        'unsung': unsung,
        'unsung_reason': unsung_reason,
        'hustle': hustle,
        'hustle_reason': hustle_reason
    }

@app.route('/sns')
@app.route('/sns/<int:gid>')
def sns_page(gid=None):
    conn = get_db()
    games = conn.execute('SELECT * FROM games ORDER BY game_date DESC LIMIT 30').fetchall()
    sel = None; recs = []; mvp_cands = []; hr_list = []; rbi_list = []; awards = {}
    if not gid and games:
        gid = games[0]['id']

    if gid:
        sel = conn.execute('SELECT * FROM games WHERE id=?',(gid,)).fetchone()
        raw_recs = conn.execute('''
            SELECT p.name,p.team,br.ab,br.hits,br.singles,br.doubles,
                   br.triples,br.hr,br.rbi,br.avg,br.slg,br.k,br.dp,br.batting_order
            FROM batting_records br JOIN players p ON p.id=br.player_id
            WHERE br.game_id=? ORDER BY br.rbi DESC, br.hits DESC, br.avg DESC
        ''',(gid,)).fetchall()

        recs = []
        for r in raw_recs:
            rd = dict(r)
            rd['mvp_pts'] = calc_mvp_points(r)
            recs.append(rd)

        mvp_cands = sorted([r for r in recs if r['ab'] > 0], key=lambda x: x['mvp_pts'], reverse=True)[:5]
        hr_list   = sorted([r for r in recs if r['hr'] > 0], key=lambda x: -x['hr'])
        rbi_list  = sorted([r for r in recs if r['rbi'] > 0], key=lambda x: -x['rbi'])
        awards    = calc_game_awards(gid)
    conn.close()
    return render_template('sns.html',
        games=games, sel=sel, records=recs,
        mvp_cands=mvp_cands, hr_list=hr_list, rbi_list=rbi_list,
        awards=awards, gid=gid, fmt_date=fmt_date)

@app.route('/api/sns/generate', methods=['POST'])
def sns_generate():
    d = request.get_json()
    gid  = d.get('game_id')
    mvp  = d.get('mvp','').strip()
    conn = get_db()
    game = conn.execute('SELECT * FROM games WHERE id=?',(gid,)).fetchone()
    if not game: return jsonify({'err':'없음'}),404
    recs = conn.execute('''
        SELECT p.name,p.team,br.ab,br.hits,br.singles,br.doubles,
               br.triples,br.hr,br.rbi,br.avg,br.slg,br.k,br.dp
        FROM batting_records br JOIN players p ON p.id=br.player_id
        WHERE br.game_id=? ORDER BY br.avg DESC,br.hits DESC
    ''',(gid,)).fetchall()
    conn.close()

    gnum     = game['game_number'] or '?'
    dstr     = fmt_date(game['game_date'])
    ws_score = game['world_score'] if game['world_score'] is not None else '?'
    bs_score = game['believers_score'] if game['believers_score'] is not None else '?'

    rec_list = []
    for r in recs:
        rd = dict(r)
        rd['mvp_pts'] = calc_mvp_points(r)
        rec_list.append(rd)

    distinct_teams = sorted(list(set(r['team'] for r in rec_list)))
    def ts(rs):
        ab=sum(r['ab'] for r in rs); h=sum(r['hits'] for r in rs)
        hr=sum(r['hr'] for r in rs)
        rbi=sum(r['rbi'] for r in rs)
        return ab,h,hr,rbi,(round(h/ab,3) if ab>0 else 0)
    
    team_stats_blocks = []
    for tname in distinct_teams:
        trs = [r for r in rec_list if r['team']==tname]
        tab, th, thr, trbi, tavg = ts(trs)
        team_stats_blocks.append(f"▶ {tname}\n  타수 {tab} | 안타 {th} | 타율 {tavg:.3f} | 홈런 {thr} | 타점 {trbi}")
    
    team_stats_str = "\n\n".join(team_stats_blocks)

    sorted_hitters = sorted([r for r in rec_list if r['ab'] > 0], key=lambda x: x['mvp_pts'], reverse=True)
    hr_lead = sorted([r for r in rec_list if r['hr'] > 0], key=lambda x: -x['hr'])
    rbi_lead = sorted([r for r in rec_list if r['rbi'] > 0], key=lambda x: -x['rbi'])

    # MVP 및 특별 시상자 (MIP, 언성히어로, 허슬플레이어) 산정
    awards = calc_game_awards(gid)
    mip_input    = d.get('mip', '').strip()
    unsung_input = d.get('unsung', '').strip()
    hustle_input = d.get('hustle', '').strip()

    def get_row(name):
        for r in rec_list:
            if r['name'] == name: return r
        return None

    # MVP
    mvp_row = None
    if mvp: mvp_row = get_row(mvp)
    if not mvp_row and sorted_hitters: mvp_row = sorted_hitters[0]

    mvp_detail = ""
    if mvp_row:
        mvp_name = mvp_row['name']
        mvp_pts = mvp_row.get('mvp_pts', calc_mvp_points(mvp_row))
        mvp_detail = f" [🔥 종합 {mvp_pts}점 | {mvp_row['ab']}타수 {mvp_row['hits']}안타 {mvp_row['rbi']}타점"
        if mvp_row['hr'] > 0: mvp_detail += f" {mvp_row['hr']}홈런"
        mvp_detail += f", 타율 {mvp_row['avg']:.3f}]"
    else:
        mvp_name = mvp or '—'

    # MIP (기량 발전상)
    mip_row = get_row(mip_input) if mip_input else awards.get('mip')
    mip_name = mip_row['name'] if mip_row else ''
    mip_detail = ""
    if mip_row:
        if awards.get('mip') and mip_name == awards['mip']['name'] and awards.get('mip_reason'):
            mip_detail = f" {awards['mip_reason']}"
        else:
            mip_detail = f" {mip_row['ab']}타수 {mip_row['hits']}안타 (타율 {mip_row['avg']:.3f}) 눈부신 기량 발전!"

    # Unsung Hero (숨은 공로상)
    unsung_row = get_row(unsung_input) if unsung_input else awards.get('unsung')
    unsung_name = unsung_row['name'] if unsung_row else ''
    unsung_detail = ""
    if unsung_row:
        if awards.get('unsung') and unsung_name == awards['unsung']['name'] and awards.get('unsung_reason'):
            unsung_detail = f" {awards['unsung_reason']}"
        else:
            unsung_detail = f" {unsung_row['batting_order']}번 타순 {unsung_row['ab']}타수 {unsung_row['hits']}안타 {unsung_row['rbi']}타점 팀 헌신!"

    # Hustle Player (열정 투혼상)
    hustle_row = get_row(hustle_input) if hustle_input else awards.get('hustle')
    hustle_name = hustle_row['name'] if hustle_row else ''
    hustle_detail = ""
    if hustle_row:
        if awards.get('hustle') and hustle_name == awards['hustle']['name'] and awards.get('hustle_reason'):
            hustle_detail = f" {awards['hustle_reason']}"
        else:
            hustle_detail = f" 삼진 {hustle_row['k']}개 {hustle_row['ab']}타수 전력 배팅과 투혼!"

    special_awards_lines = []
    if mip_name and mip_name != mvp_name:
        special_awards_lines.append(f"✨ MIP (기량 발전상): {mip_name} 형제 [{mip_detail.strip()}]")
    if unsung_name and unsung_name != mvp_name and unsung_name != mip_name:
        special_awards_lines.append(f"🛡️ 언성 히어로 (숨은 공로상): {unsung_name} 형제 [{unsung_detail.strip()}]")
    if hustle_name and hustle_name != mvp_name and hustle_name != mip_name and hustle_name != unsung_name:
        special_awards_lines.append(f"🔥 허슬 플레이어 (열정 투혼상): {hustle_name} 형제 [{hustle_detail.strip()}]")

    special_awards_str = ("\n" + "\n".join(special_awards_lines)) if special_awards_lines else ""

    hr_line = ''
    if hr_lead:
        hr_line = '\n💣 홈런: ' + '  '.join([f"{r['name']} {r['hr']}방🚀" for r in hr_lead])

    rbi_line = ""
    if rbi_lead:
        rbi_line = "\n🎯 타점왕(해결사): " + "  ".join([f"{r['name']} {r['rbi']}타점" for r in rbi_lead[:3]])

    medals = ['🥇','🥈','🥉','  4','  5']
    top5 = ''
    for i, r in enumerate(sorted_hitters[:5]):
        m = medals[i] if i < 3 else f'  {i+1}'
        top5 += f"\n   {m} {r['name']}  {r['mvp_pts']}점 ({r['ab']}타수 {r['hits']}안타 {r['rbi']}타점"
        if r['hr'] > 0: top5 += f" {r['hr']}홈런"
        top5 += f" 타율 {r['avg']:.3f})"

    long_msg = f"""⚾ W.B.C {gnum}번째 경기 결과! ⚾

🌍 세계로교회 World Believers Club
📅 {dstr}

━━━━━━━━━━━━━━━━━━━━━
🏆 경기 결과
━━━━━━━━━━━━━━━━━━━━━

⚡ World Team       {ws_score}점
🔥 Believers Team   {bs_score}점

━━━━━━━━━━━━━━━━━━━━━
📊 팀 타격 기록
━━━━━━━━━━━━━━━━━━━━━

{team_stats_str}

━━━━━━━━━━━━━━━━━━━━━
🎊 오늘의 영예의 시상 (Awards)
━━━━━━━━━━━━━━━━━━━━━

🏅 MVP: {mvp_name} 형제{mvp_detail}{special_awards_str}{rbi_line}{hr_line}

📈 활약 타자 TOP 5 (가중치 종합점수순){top5}

━━━━━━━━━━━━━━━━━━━━━

믿음으로 스윙하라, 세계로 나아가라! ⚾🙏

#세계로교회 #WBC #WorldBelieversClub
#스크린야구 #전도회 #야빠"""

    short_mip_str = f"\n✨ MIP (기량발전): {mip_name} 형제" if mip_name else ""
    short_unsung_str = f"\n🛡️ 언성 히어로: {unsung_name} 형제" if unsung_name else ""

    lead_hitter_info = "—"
    if sorted_hitters:
        lh = sorted_hitters[0]
        lead_hitter_info = f"{lh['name']} [🔥 {lh['mvp_pts']}점] ({lh['ab']}타수 {lh['hits']}안타 {lh['rbi']}타점 타율 {lh['avg']:.3f})"

    short_msg = f"""⚾ W.B.C 경기 결과 | {dstr}

⚡ World Team  {ws_score}점
🔥 Believers  {bs_score}점

🏅 MVP: {mvp_name} 형제{mvp_detail}{short_mip_str}{short_unsung_str}
🎯 경기 최고 활약(종합 1위): {lead_hitter_info}
{rbi_line}{hr_line}

오늘도 감사합니다 🙏 믿음으로 스윙하라! ⚾

#세계로교회 #WBC #스크린야구 #야빠"""

    return jsonify({'long': long_msg, 'short': short_msg})

@app.route('/players')
@admin_required
def players_page():
    conn = get_db()
    pl = conn.execute('''
        SELECT p.*,COUNT(DISTINCT br.game_id) gc
        FROM players p LEFT JOIN batting_records br ON br.player_id=p.id
        GROUP BY p.id ORDER BY p.team,p.id
    ''').fetchall()
    conn.close()
    return render_template('players.html', players=pl)

@app.route('/players/add', methods=['POST'])
@admin_required
def player_add():
    name = request.form.get('name','').strip()
    team = request.form.get('team','')
    if name and team in ('World','Believers'):
        conn = get_db()
        conn.execute('INSERT INTO players(name,team) VALUES(?,?)',(name,team))
        conn.commit(); conn.close()
        flash(f'✅ {name} 선수가 추가되었습니다.','success')
    return redirect(url_for('players_page'))

@app.route('/players/<int:pid>/toggle', methods=['POST'])
@admin_required
def player_toggle(pid):
    conn = get_db()
    conn.execute('UPDATE players SET is_active=1-is_active WHERE id=?',(pid,))
    conn.commit(); conn.close()
    return redirect(url_for('players_page'))

@app.route('/api/export/excel/<int:gid>')
def export_excel(gid):
    try: import openpyxl
    except: return '패키지 없음',500
    from openpyxl.styles import Font,PatternFill,Alignment
    conn = get_db()
    game = conn.execute('SELECT * FROM games WHERE id=?',(gid,)).fetchone()
    recs = conn.execute('''
        SELECT p.name,p.team,br.batting_order,
               br.inn1,br.inn2,br.inn3,br.inn4,br.inn5,br.inn6,br.inn7,
               br.inn8,br.inn9,br.inn10,br.inn11,br.inn12,br.inn13,
               br.ab,br.hits,br.singles,br.doubles,br.triples,br.hr,
               br.rbi,br.k,br.out_count,br.dp,br.avg,br.slg,br.obp
        FROM batting_records br JOIN players p ON p.id=br.player_id
        WHERE br.game_id=? ORDER BY br.team,br.batting_order
    ''',(gid,)).fetchall()
    conn.close()
    wb = openpyxl.Workbook(); ws = wb.active
    ws.title = f"{game['game_date']} 기록"
    hdr = ['타순','선수명','팀','1이닝','2이닝','3이닝','4이닝','5이닝',
           '6이닝','7이닝','8이닝','9이닝','10이닝','11이닝','12이닝','13이닝',
           '타수','안타','1루타','2루타','3루타','홈런','타점','삼진','아웃','병살','타율','장타율','출루율']
    hfill = PatternFill("solid",fgColor="1F4E79")
    hfont = Font(bold=True,color="FFFFFF")
    for ci,h in enumerate(hdr,1):
        c=ws.cell(1,ci,h); c.fill=hfill; c.font=hfont
        c.alignment=Alignment(horizontal='center')
    for ri,r in enumerate(recs,2):
        for ci,v in enumerate([r['batting_order'],r['name'],r['team'],
            r['inn1'],r['inn2'],r['inn3'],r['inn4'],r['inn5'],r['inn6'],r['inn7'],
            r['inn8'],r['inn9'],r['inn10'],r['inn11'],r['inn12'],r['inn13'],
            r['ab'],r['hits'],r['singles'],r['doubles'],r['triples'],r['hr'],
            r['rbi'],r['k'],r['out_count'],r['dp'],r['avg'],r['slg'],r['obp']],1):
            ws.cell(ri,ci,v)
    buf = io.BytesIO(); wb.save(buf); buf.seek(0)
    return send_file(buf,
        download_name=f"WBC_{game['game_date']}_경기기록.xlsx",
        as_attachment=True,
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')

@app.route('/api/players')
def api_players():
    conn = get_db()
    pl = conn.execute(
        'SELECT * FROM players WHERE is_active=1 ORDER BY team,id'
    ).fetchall()
    conn.close()
    return jsonify([dict(p) for p in pl])

@app.route('/analytics')
def analytics_page():
    pid = request.args.get('player_id', type=int)
    conn = get_db()
    players = conn.execute('SELECT id, name, team FROM players WHERE is_active=1 ORDER BY team, name').fetchall()
    sel_player = None
    if pid:
        sel_player = conn.execute('SELECT * FROM players WHERE id=?', (pid,)).fetchone()
    if not sel_player and players:
        top_p = conn.execute('''
            SELECT p.*, COUNT(br.id) gc 
            FROM players p JOIN batting_records br ON br.player_id=p.id
            GROUP BY p.id ORDER BY gc DESC, p.id ASC LIMIT 1
        ''').fetchone()
        sel_player = top_p if top_p else players[0]
    conn.close()
    return render_template('analytics.html', players=players, sel_player=sel_player)

@app.route('/api/analytics/player/<int:pid>')
def api_analytics_player(pid):
    conn = get_db()
    player = conn.execute('SELECT * FROM players WHERE id=?', (pid,)).fetchone()
    if not player:
        conn.close()
        return jsonify({'err': '선수 없음'}), 404

    recs = conn.execute('''
        SELECT g.id as game_id, g.game_date, g.game_number,
               br.ab, br.hits, br.singles, br.doubles, br.triples, br.hr,
               br.rbi, br.k, br.dp, br.avg, br.slg, br.team
        FROM batting_records br
        JOIN games g ON g.id = br.game_id
        WHERE br.player_id = ?
        ORDER BY g.game_date ASC, g.id ASC
    ''', (pid,)).fetchall()
    conn.close()

    timeline = []
    run_ab = 0
    run_hits = 0
    run_hr = 0
    run_rbi = 0
    run_pts = 0.0

    for r in recs:
        game_ab = r['ab'] or 0
        game_hits = r['hits'] or 0
        game_hr = r['hr'] or 0
        game_rbi = r['rbi'] or 0
        game_avg = r['avg'] or 0.0
        game_pts = calc_mvp_points(r)

        run_ab += game_ab
        run_hits += game_hits
        run_hr += game_hr
        run_rbi += game_rbi
        run_pts += game_pts

        c_avg = round(run_hits / run_ab, 3) if run_ab > 0 else 0.0

        label = f"{r['game_number']}회차 ({fmt_date(r['game_date'])})"
        timeline.append({
            'game_id': r['game_id'],
            'game_number': r['game_number'],
            'game_date': r['game_date'],
            'label': label,
            'team': r['team'],
            'ab': game_ab,
            'hits': game_hits,
            'singles': r['singles'] or 0,
            'doubles': r['doubles'] or 0,
            'triples': r['triples'] or 0,
            'hr': game_hr,
            'rbi': game_rbi,
            'k': r['k'] or 0,
            'dp': r['dp'] or 0,
            'game_avg': game_avg,
            'cum_avg': c_avg,
            'game_pts': game_pts,
            'cum_pts': round(run_pts, 1)
        })

    total_games = len(recs)
    overall_avg = round(run_hits / run_ab, 3) if run_ab > 0 else 0.0
    rbi_per_game = round(run_rbi / total_games, 2) if total_games > 0 else 0.0
    hr_per_game = round(run_hr / total_games, 2) if total_games > 0 else 0.0
    avg_pts = round(run_pts / total_games, 1) if total_games > 0 else 0.0

    # 5대 핵심 지표 산출 (100점 만점 정규화)
    contact_score = min(100, max(20, round(overall_avg * 120 + 20)))
    total_slg = round(sum(r['slg'] or 0 for r in recs) / total_games, 3) if total_games > 0 else 0.0
    power_score = min(100, max(20, round(total_slg * 50 + (hr_per_game * 25))))
    clutch_score = min(100, max(20, round(25 + rbi_per_game * 18)))
    total_k = sum(r['k'] or 0 for r in recs)
    k_rate = (total_k / run_ab) if run_ab > 0 else 0.0
    discipline_score = min(100, max(30, round(95 - k_rate * 80)))
    impact_score = min(100, max(20, round(25 + avg_pts * 3.2)))

    radar = {
        'contact': contact_score,
        'power': power_score,
        'clutch': clutch_score,
        'discipline': discipline_score,
        'impact': impact_score
    }

    best_game = max(timeline, key=lambda x: x['game_pts']) if timeline else None

    trend = '유지'
    if len(timeline) >= 2:
        last_g = timeline[-1]
        prev_g = timeline[-2]
        if last_g['cum_avg'] > prev_g['cum_avg'] + 0.01:
            trend = '상승세 🔥'
        elif last_g['cum_avg'] < prev_g['cum_avg'] - 0.01:
            trend = '조정기 💤'
    elif len(timeline) == 1:
        trend = '첫 경기 순항 🚀'

    return jsonify({
        'player': dict(player),
        'total_games': total_games,
        'total_ab': run_ab,
        'total_hits': run_hits,
        'total_hr': run_hr,
        'total_rbi': run_rbi,
        'overall_avg': overall_avg,
        'avg_pts': avg_pts,
        'radar': radar,
        'trend': trend,
        'best_game': best_game,
        'timeline': timeline
    })

@app.route('/api/analytics/teams')
def api_analytics_teams():
    conn = get_db()
    games = conn.execute('SELECT id, game_date, game_number, world_score, believers_score FROM games ORDER BY game_date ASC, id ASC').fetchall()
    conn.close()
    return jsonify({'games': [dict(g) for g in games]})

def get_player_report_data(pid):
    conn = get_db()
    player = conn.execute('SELECT * FROM players WHERE id=?', (pid,)).fetchone()
    if not player:
        conn.close()
        return None

    recs = conn.execute('''
        SELECT g.id as game_id, g.game_date, g.game_number,
               br.ab, br.hits, br.singles, br.doubles, br.triples, br.hr,
               br.rbi, br.k, br.dp, br.avg, br.slg, br.obp, br.team
        FROM batting_records br
        JOIN games g ON g.id = br.game_id
        WHERE br.player_id = ?
        ORDER BY g.game_date ASC, g.id ASC
    ''', (pid,)).fetchall()

    timeline = []
    run_ab = 0; run_hits = 0; run_hr = 0; run_rbi = 0; run_pts = 0.0
    run_singles = 0; run_doubles = 0; run_triples = 0; run_k = 0; run_dp = 0

    for r in recs:
        game_ab = r['ab'] or 0
        game_hits = r['hits'] or 0
        game_hr = r['hr'] or 0
        game_rbi = r['rbi'] or 0
        game_avg = r['avg'] or 0.0
        game_pts = calc_mvp_points(r)

        run_ab += game_ab
        run_hits += game_hits
        run_hr += game_hr
        run_rbi += game_rbi
        run_pts += game_pts
        run_singles += (r['singles'] or 0)
        run_doubles += (r['doubles'] or 0)
        run_triples += (r['triples'] or 0)
        run_k += (r['k'] or 0)
        run_dp += (r['dp'] or 0)

        c_avg = round(run_hits / run_ab, 3) if run_ab > 0 else 0.0

        timeline.append({
            'game_id': r['game_id'],
            'game_number': r['game_number'],
            'game_date': r['game_date'],
            'label': f"{r['game_number']}회",
            'ab': game_ab,
            'hits': game_hits,
            'singles': r['singles'] or 0,
            'doubles': r['doubles'] or 0,
            'triples': r['triples'] or 0,
            'hr': game_hr,
            'rbi': game_rbi,
            'k': r['k'] or 0,
            'dp': r['dp'] or 0,
            'game_avg': game_avg,
            'cum_avg': c_avg,
            'game_pts': game_pts
        })

    total_games = len(recs)
    overall_avg = round(run_hits / run_ab, 3) if run_ab > 0 else 0.0
    overall_slg = round((run_singles + run_doubles*2 + run_triples*3 + run_hr*4) / run_ab, 3) if run_ab > 0 else 0.0
    overall_obp = overall_avg
    overall_ops = round(overall_obp + overall_slg, 3)
    rbi_per_game = round(run_rbi / total_games, 2) if total_games > 0 else 0.0
    hr_per_game = round(run_hr / total_games, 2) if total_games > 0 else 0.0
    avg_pts = round(run_pts / total_games, 1) if total_games > 0 else 0.0

    # 5대 능력치 레이더
    contact_score = min(100, max(20, round(overall_avg * 120 + 20)))
    power_score = min(100, max(20, round(overall_slg * 50 + (hr_per_game * 25))))
    clutch_score = min(100, max(20, round(25 + rbi_per_game * 18)))
    k_rate = (run_k / run_ab) if run_ab > 0 else 0.0
    discipline_score = min(100, max(30, round(95 - k_rate * 80)))
    impact_score = min(100, max(20, round(25 + avg_pts * 3.2)))

    radar = {
        'contact': contact_score,
        'power': power_score,
        'clutch': clutch_score,
        'discipline': discipline_score,
        'impact': impact_score
    }

    # 타자 스타일 타이틀
    if overall_avg >= 0.6 and run_hr >= 2:
        style_title = "전천후 슈퍼 슬러거 (Super Slugger)"
    elif run_hr >= 1 or overall_slg >= 0.8:
        style_title = "클러치 파워 히터 (Power Hitter)"
    elif overall_avg >= 0.5:
        style_title = "정밀 타격 마스터 (Precision Contact)"
    elif run_rbi >= 2:
        style_title = "찬스 해결사 (Clutch Specialist)"
    elif discipline_score >= 90:
        style_title = "안정적인 출루형 타자 (On-Base Machine)"
    else:
        style_title = "성장형 올라운드 플레이어 (Rising All-Rounder)"

    # 시상 횟수 집계
    all_game_ids = [g[0] for g in conn.execute('SELECT id FROM games').fetchall()]
    mvp_count = 0
    mip_count = 0
    unsung_count = 0
    for gid in all_game_ids:
        aw = calc_game_awards(gid)
        if aw.get('mvp') and aw['mvp']['player_id'] == pid:
            mvp_count += 1
        if aw.get('mip') and aw['mip']['player_id'] == pid:
            mip_count += 1
        if aw.get('unsung') and aw['unsung']['player_id'] == pid:
            unsung_count += 1

    best_game = max(timeline, key=lambda x: x['game_pts']) if timeline else None

    conn.close()

    # 선수 맞춤형 장단점 및 개선방향 정밀 진단
    scouting = generate_player_scouting_report({
        'player': dict(player),
        'overall_avg': overall_avg,
        'overall_slg': overall_slg,
        'total_ab': run_ab,
        'total_hits': run_hits,
        'total_hr': run_hr,
        'total_rbi': run_rbi,
        'total_k': run_k,
        'total_dp': run_dp,
        'total_games': total_games,
        'radar': radar,
        'style_title': style_title
    })

    return {
        'player': dict(player),
        'total_games': total_games,
        'total_ab': run_ab,
        'total_hits': run_hits,
        'singles': run_singles,
        'doubles': run_doubles,
        'triples': run_triples,
        'total_hr': run_hr,
        'total_rbi': run_rbi,
        'total_k': run_k,
        'total_dp': run_dp,
        'overall_avg': overall_avg,
        'overall_slg': overall_slg,
        'overall_obp': overall_obp,
        'overall_ops': overall_ops,
        'avg_pts': avg_pts,
        'radar': radar,
        'style_title': style_title,
        'mvp_count': mvp_count,
        'mip_count': mip_count,
        'unsung_count': unsung_count,
        'best_game': best_game,
        'timeline': timeline,
        'scouting': scouting
    }

def generate_player_scouting_report(d):
    name = d['player']['name']
    avg = d['overall_avg']
    slg = d['overall_slg']
    ab = d['total_ab']
    hits = d['total_hits']
    hr = d['total_hr']
    rbi = d['total_rbi']
    k = d['total_k']
    dp = d['total_dp']
    games = d['total_games']
    
    k_rate = (k / ab) if ab > 0 else 0.0
    rbi_per_game = (rbi / games) if games > 0 else 0.0
    
    strengths = []
    weaknesses = []
    action_plans = []
    
    # 1. 핵심 강점 (Strengths)
    if hr >= 2 or (hr >= 1 and slg >= 0.8):
        strengths.append({
            'badge': '장타력 폭발',
            'title': '담장을 넘기는 리그 정상급 파워 스윙',
            'desc': f'누적 {hr}홈런, 장타율 {slg:.3f}의 파괴력으로 일발 장타를 생산하는 하체 회전력과 배트 스피드가 압도적입니다.'
        })
    elif hr == 1:
        strengths.append({
            'badge': '장타 잠재력',
            'title': '언제든 담장을 위협하는 펀치력 보유',
            'desc': f'결정적인 한 방(1홈런)을 쳐낼 수 있는 파워 포텐셜을 갖추어 상대 투수에게 큰 위압감을 선사합니다.'
        })

    if avg >= 0.6:
        strengths.append({
            'badge': '정밀 컨택',
            'title': '어떤 코스도 안타로 만드는 정교한 배트 컨트롤',
            'desc': f'시즌 타율 {avg:.3f}의 경이로운 컨택 능력으로 투수의 공을 결대로 받아치는 스프레이 히팅이 일품입니다.'
        })
    elif avg >= 0.4:
        strengths.append({
            'badge': '안정적 컨택',
            'title': '높은 집중력과 견고한 타격 밸런스',
            'desc': f'타율 {avg:.3f}로 타석마다 흔들림 없는 밸런스를 유지하며 양질의 정타를 꾸준히 생산하고 있습니다.'
        })
    
    if rbi >= 3 or rbi_per_game >= 2.0:
        strengths.append({
            'badge': '찬스 해결사',
            'title': '주자를 모두 불러들이는 클러치 히팅',
            'desc': f'총 {rbi}타점(경기당 {rbi_per_game:.1f}점)을 기록하며 득점권 찬스에서 승부를 결정짓는 집중력이 탁월합니다.'
        })
    elif rbi >= 1:
        strengths.append({
            'badge': '타점 생산력',
            'title': '팀 배팅과 득점 기회에서의 해결 의지',
            'desc': f'주자 출루 시 적극적인 배팅으로 귀중한 {rbi}타점을 수확하며 팀 득점의 윤활유 역할을 완벽히 수행합니다.'
        })
        
    if k == 0 and ab >= 3:
        strengths.append({
            'badge': '무삼진/선구안',
            'title': '단 1개의 삼진도 허용하지 않은 완벽한 컨택 존',
            'desc': f'{ab}타석 무삼진으로 불리한 볼카운트에서도 반드시 인플레이 타구를 만들어내는 끈질김을 보유했습니다.'
        })
    elif k_rate <= 0.15 and ab >= 4:
        strengths.append({
            'badge': '선구안 안정',
            'title': '스트라이크 존에 대한 뛰어난 판별력',
            'desc': f'낮은 삼진율({k_rate*100:.1f}%)로 유인구에 쉽게 속지 않고 본인의 히팅 존을 철저하게 지켜냅니다.'
        })

    if dp == 0 and ab >= 3:
        strengths.append({
            'badge': '작전 수행',
            'title': '병살타 0개의 팀 공격 흐름 유지',
            'desc': '주자 출루 상황에서도 병살타 없이 안정적인 타격을 선보여 공격 흐름을 원활하게 이어갑니다.'
        })

    if len(strengths) == 0:
        strengths.append({
            'badge': '적극성',
            'title': '자신감 있는 스윙과 과감한 타석 어프로치',
            'desc': '타석에서 주저함 없이 본인의 스윙 궤적을 과감하게 가져가며 강한 타구를 생산할 잠재력이 충분합니다.'
        })

    # 2. 보완점 및 주의사항 (Weaknesses & Focus)
    if k >= 3 or k_rate >= 0.35:
        weaknesses.append({
            'badge': '유인구 대처',
            'title': '2스트라이크 이후 바깥쪽/낮은 공 유인구 헛스윙 관리',
            'desc': f'삼진율({k_rate*100:.1f}%) 관리를 위해 볼카운트가 몰렸을 때 존을 벗어나는 유인구를 골라내는 선구안 보완이 요구됩니다.'
        })
    elif k >= 1:
        weaknesses.append({
            'badge': '선구안 보강',
            'title': '결정구 타격 시 히팅 포인트 흔들림 방지',
            'desc': '유리한 카운트에서는 좋은 타구가 나오나, 2스트라이크 이후 떨어지는 변화구에 배트가 끌려나가지 않도록 주의해야 합니다.'
        })

    if hr == 0 and (slg - avg) < 0.1 and hits >= 1:
        weaknesses.append({
            'badge': '장타력 보강',
            'title': '단타 위주의 타구 형성 및 타구 발사각(Launch Angle) 개선',
            'desc': '정타 비율은 우수하나 타구가 주로 내야나 낮게 형성됩니다. 공 밑을 약간 올려치는 어퍼스윙 궤도 보강이 필요합니다.'
        })
        
    if avg < 0.300 and ab >= 3:
        weaknesses.append({
            'badge': '타격 타이밍',
            'title': '패스트볼에 대한 테이크백 시점 및 배트 스타트 속도',
            'desc': '빠른 볼 타이밍에 배트가 살짝 밀려 빗맞는 경우가 있으므로 테이크백을 반 박자 일찍 준비하는 훈련이 권장됩니다.'
        })

    if rbi == 0 and ab >= 3:
        weaknesses.append({
            'badge': '찬스 멘탈',
            'title': '주자 득점권 상황에서의 불필요한 힘 빼기',
            'desc': '주자가 있을 때 장타 의식으로 상체에 힘이 들어갈 수 있으므로, 결대로 가볍게 맞힌다는 여유로운 멘탈이 필요합니다.'
        })

    if dp >= 1:
        weaknesses.append({
            'badge': '땅볼 억제',
            'title': '주자 1루 상황 시 내야 땅볼 타구 억제',
            'desc': f'병살타 {dp}개를 기록한 바 있어 주자가 있을 때는 롤오버 땅볼보다는 공을 외야로 띄우는 어프로치가 중요합니다.'
        })

    if len(weaknesses) == 0:
        weaknesses.append({
            'badge': '타격 일관성',
            'title': '상대 팀의 집중 견제 대비 및 체력 안배',
            'desc': '탁월한 타격감으로 상대 투수진의 집중 표적이 될 수 있으므로, 매 타석 일정한 루틴과 집중력 유지가 핵심입니다.'
        })

    # 3. 개선 방향 및 훈련 솔루션 (Improvement Action Plan)
    if k_rate >= 0.25 or avg < 0.300:
        action_plans.append({
            'focus': '타석 접근법',
            'title': '2스트라이크 투혼: 배트 1인치 짧게 쥐고 컨택 존 형성',
            'desc': '카운트가 불리할 때는 풀스윙 대신 배트를 짧게 쥐고 센터 방면으로 결대로 가볍게 툭 맞히는 컨택 위주 승부 권장.'
        })
    else:
        action_plans.append({
            'focus': '히팅 노림수',
            'title': '초구 및 유리한 카운트에서 자신 있는 코스 전력 배팅',
            'desc': '가장 자신 있는 코스 하나만 미리 노려두고 그 존으로 들어오는 공에는 초구부터 지체 없이 풀스윙으로 공략.'
        })

    if hr == 0 and slg < 0.5:
        action_plans.append({
            'focus': '스윙 궤적',
            'title': '하체 중심 이동 및 10~15도 발사각 어퍼 블로우 연습',
            'desc': '타격 시 앞발을 단단히 고정하고 골반 회전의 반동을 이용해 타구를 외야로 띄워 보내는 장타 메커니즘 훈련 추천.'
        })
    else:
        action_plans.append({
            'focus': '코스 공략',
            'title': '우중간을 가르는 스프레이 히터(Spray Hitter)로의 진화',
            'desc': '당겨치기에 그치지 않고 바깥쪽 코스를 우중간으로 결대로 밀어쳐 장타를 생산하면 상대 수비 시프트를 완벽히 무력화 가능.'
        })

    # 4. 코칭스태프 종합 총평
    if avg >= 0.5 or hr >= 1:
        coach_comment = f"{name} 선수는 팀 타선의 기둥이자 승부처를 직접 지배하는 특급 해결사입니다. 이미 증명된 강력한 스윙 궤적과 타격 자신감을 계속 유지한다면 이번 시즌 팀의 우승과 리그 최고 타자 타이틀을 동시에 거머쥘 것입니다."
    elif avg >= 0.3 or rbi >= 1:
        coach_comment = f"{name} 선수는 팀 배팅과 클러치 상황에서의 센스가 돋보이는 핵심 플레이어입니다. 타격 타이밍과 볼카운트별 접근법을 조금만 더 정교하게 다듬는다면 매 경기 멀티히트와 대량 타점을 쏟아낼 잠재력을 갖추고 있습니다."
    else:
        coach_comment = f"{name} 선수는 타석에서의 뜨거운 승부욕과 무한한 성장 잠재력을 지닌 선수입니다. 첫 경기의 경험을 발판 삼아 몸의 힘을 빼고 센터 방면으로 가볍게 결대로 맞히는 연습을 꾸준히 이어간다면 다음 경기에서 눈부신 반등을 보여줄 것입니다."

    return {
        'strengths': strengths[:3],
        'weaknesses': weaknesses[:2],
        'action_plans': action_plans[:2],
        'coach_comment': coach_comment
    }

@app.route('/report/player/<int:pid>')
def report_player(pid):
    data = get_player_report_data(pid)
    if not data:
        flash('선수를 찾을 수 없습니다.', 'danger')
        return redirect(url_for('analytics_page'))
    last_game_date = data['timeline'][-1]['game_date'] if data['timeline'] else date.today().strftime('%Y-%m-%d')
    pname = data['player']['name']
    doc_title = f"WBC_전력분석리포트_{last_game_date}_{pname}"
    return render_template('report_player.html', reports=[data], is_single=True, doc_title=doc_title, last_game_date=last_game_date, fmt_date=fmt_date)

@app.route('/report/all')
def report_all():
    conn = get_db()
    players = conn.execute('SELECT id FROM players WHERE is_active=1 ORDER BY team, name').fetchall()
    latest_game = conn.execute('SELECT game_date FROM games ORDER BY game_date DESC, id DESC LIMIT 1').fetchone()
    conn.close()
    last_game_date = latest_game['game_date'] if latest_game else date.today().strftime('%Y-%m-%d')
    reports = []
    for p in players:
        d = get_player_report_data(p['id'])
        if d and d['total_games'] > 0:
            reports.append(d)
    doc_title = f"WBC_전체선수_전력분석리포트_{last_game_date}"
    return render_template('report_player.html', reports=reports, is_single=False, doc_title=doc_title, last_game_date=last_game_date, fmt_date=fmt_date)

if __name__ == '__main__':
    init_db()
    print('\n' + '='*52)
    print(' [W.B.C Screen Baseball Management System]')
    print(' World Believers Club')
    print('='*52)
    print(' * Web URL    : http://localhost:5000')
    print(' * Mobile URL : http://[YOUR-PC-IP]:5000')
    print(' * Stop server: Press Ctrl+C')
    print('='*52 + '\n')
    app.run(debug=False, host='0.0.0.0', port=5000)