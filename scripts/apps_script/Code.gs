/**
 * Yielda — 분석 수집(Analysis Data Collection) 웹앱.
 *
 * 백엔드(`app/services/sheets_logger.py`)가 분석 1건마다 이 스크립트에 POST 하고,
 * 스크립트는 시트에 한 행을 append 한다. 같은 스크립트의 doGet 은 수집 대시보드가
 * 행을 되읽을 때 쓴다. 서버도 DB도 없다.
 *
 * 배포 방법은 같은 폴더의 README.md 참고.
 *
 * ## 열 관리
 * 열 순서의 정본은 **백엔드의 `COLUMNS`** 다. 이 스크립트는 헤더를 스스로 맞춘다:
 *   - 시트가 비어 있으면 받은 columns 를 그대로 헤더로 쓴다
 *   - 새 열이 생기면 헤더 **오른쪽 끝에 덧붙인다** (기존 데이터 정렬을 깨지 않는다)
 *   - 열이 빠지면 헤더에 그대로 남고 새 행에서는 빈 셀이 된다
 * 그래서 기획이 열을 확정할 때 백엔드만 고치면 되고 시트를 손댈 필요가 없다.
 *
 * ## 시트 관리
 * 헤더가 새로 만들어지거나 열이 추가될 때 `formatSheet_()` 가 한 번 돌아
 * 고정 행·필터·열 너비·숫자 서식·결과별 색을 잡아 준다. 시트 메뉴
 * (**Yielda 수집**) 에서 언제든 다시 적용할 수 있고, 요약 탭도 여기서 만든다.
 */

/** 원본 데이터 탭. */
var SHEET_NAME = 'analyses';
/** 수식으로 자동 갱신되는 요약 탭. */
var SUMMARY_SHEET = '요약';

/**
 * 공유 토큰. 스크립트 속성(Project Settings → Script properties)에
 * `TOKEN` 으로 넣고, 백엔드 `.env` 의 `SHEETS_WEBHOOK_TOKEN` 과 같은 값으로 맞춘다.
 * 비워 두면 토큰 검사를 건너뛴다(URL 만으로 접근 가능 — 내부 데모에서만 권장).
 */
function expectedToken_() {
  return PropertiesService.getScriptProperties().getProperty('TOKEN') || '';
}

/** 열별 숫자 서식. 없으면 자동(일반). */
var NUMBER_FORMATS = {
  // ISO8601 문자열 그대로 둔다. Date 로 바꾸면 +09:00 이 사라지고, 로케일에 따라
  // 11/08 이 8월 11일로도 11월 8일로도 읽힌다. 텍스트지만 ISO 라 정렬은 정확하다.
  timestamp: '@',
  biz_no: '@',
  input_place_id: '@',
  kakao_place_id: '@',
  phone: '@',
  rating: '0.0',
  review_count: '#,##0',
  reviews_analyzed: '#,##0',
  web_evidence_count: '#,##0',
  duration_ms: '#,##0',
  music_pool_size: '#,##0',
  district_total_places: '#,##0',
  district_univ_count: '#,##0',
  lat: '0.000000',
  lng: '0.000000',
  weather_temp_c: '0.0',
  district_confidence: '0.00',
  consistency_score: '0.00',
  ambience_confidence: '0.00',
  district_cafe_pct: '0.0',
  district_food_pct: '0.0',
  district_bank_pct: '0.0',
  district_edu_pct: '0.0'
};

/** 열별 너비(px). 없으면 DEFAULT_WIDTH. */
var COLUMN_WIDTHS = {
  timestamp: 160,
  outcome: 90,
  client: 80,
  biz_no: 110,
  store_name: 200,
  category: 110,
  category_full: 220,
  address: 240,
  region_address: 220,
  hours: 300,
  district_criteria: 320,
  review_keywords: 260,
  top_tracks: 260,
  playlist_label: 200,
  tpo_place: 180,
  error: 260,
  kakao_place_url: 140
};
var DEFAULT_WIDTH = 110;

/** 표에서 좌측에 고정할 열 수 (timestamp · outcome · client · biz_no). */
var FROZEN_COLUMNS = 4;

function json_(payload) {
  return ContentService
    .createTextOutput(JSON.stringify(payload))
    .setMimeType(ContentService.MimeType.JSON);
}

function checkToken_(given) {
  var expected = expectedToken_();
  if (!expected) return true;
  return String(given || '') === expected;
}

function sheet_() {
  var ss = SpreadsheetApp.getActiveSpreadsheet();
  var sheet = ss.getSheetByName(SHEET_NAME);
  if (!sheet) {
    sheet = ss.insertSheet(SHEET_NAME);
  }
  return sheet;
}

function header_(sheet) {
  var lastCol = sheet.getLastColumn();
  if (lastCol < 1) return [];
  return sheet.getRange(1, 1, 1, lastCol).getValues()[0]
    .map(function (h) { return String(h || '').trim(); });
}

/** 헤더를 받은 columns 와 합친다. 반환값이 실제 열 순서다. */
function syncHeader_(sheet, columns) {
  var header = header_(sheet).filter(function (h) { return h !== ''; });

  var added = (columns || []).filter(function (c) { return header.indexOf(c) === -1; });
  if (added.length === 0) return header;

  header = header.concat(added);
  sheet.getRange(1, 1, 1, header.length).setValues([header]);
  // 열이 바뀔 때만 서식을 다시 잡는다 — append 마다 하면 느려진다.
  formatSheet_(sheet, header);
  return header;
}

// ---------------------------------------------------------------------------
// 시트 서식 — 59열을 사람이 읽을 수 있게 만든다
// ---------------------------------------------------------------------------
function formatSheet_(sheet, header) {
  header = header || header_(sheet);
  if (header.length === 0) return;

  var maxRows = Math.max(sheet.getMaxRows(), 2);

  // 1) 헤더 고정 + 스타일
  sheet.setFrozenRows(1);
  sheet.setFrozenColumns(Math.min(FROZEN_COLUMNS, header.length));
  sheet.getRange(1, 1, 1, header.length)
    .setFontWeight('bold')
    .setBackground('#0e1316')
    .setFontColor('#ffffff')
    .setVerticalAlignment('middle')
    .setWrap(false);
  sheet.setRowHeight(1, 32);

  // 2) 열 너비 + 숫자 서식
  for (var i = 0; i < header.length; i++) {
    var name = header[i];
    sheet.setColumnWidth(i + 1, COLUMN_WIDTHS[name] || DEFAULT_WIDTH);
    var format = NUMBER_FORMATS[name];
    if (format && maxRows > 1) {
      sheet.getRange(2, i + 1, maxRows - 1, 1).setNumberFormat(format);
    }
  }

  // 3) 전체 필터 — 기획이 시트에서 바로 정렬·필터할 수 있게
  var existing = sheet.getFilter();
  if (existing) existing.remove();
  sheet.getRange(1, 1, maxRows, header.length).createFilter();

  // 4) 줄무늬 — 59열을 가로로 훑을 때 행을 놓치지 않게
  sheet.getBandings().forEach(function (b) { b.remove(); });
  sheet.getRange(1, 1, maxRows, header.length)
    .applyRowBanding(SpreadsheetApp.BandingTheme.LIGHT_GREY, true, false);

  // 5) 결과·품질에 따른 색. 행 전체를 칠해 스캔 한 번에 문제가 보이게 한다.
  applyConditionalFormats_(sheet, header, maxRows);

  // 6) 헤더는 실수로 못 고치게 잠근다 — 열 이름이 백엔드와 어긋나면 매핑이 깨진다.
  protectHeader_(sheet, header);
}

function colLetter_(index /* 1-based */) {
  var letter = '';
  while (index > 0) {
    var rem = (index - 1) % 26;
    letter = String.fromCharCode(65 + rem) + letter;
    index = Math.floor((index - 1) / 26);
  }
  return letter;
}

function applyConditionalFormats_(sheet, header, maxRows) {
  var range = sheet.getRange(2, 1, maxRows - 1, header.length);
  var rules = [];

  function ruleOn(column, formula, background, fontColor) {
    var idx = header.indexOf(column);
    if (idx === -1) return;
    var ref = '$' + colLetter_(idx + 1) + '2';
    var builder = SpreadsheetApp.newConditionalFormatRule()
      .whenFormulaSatisfied(formula.replace(/\{REF\}/g, ref))
      .setRanges([range]);
    if (background) builder.setBackground(background);
    if (fontColor) builder.setFontColor(fontColor);
    rules.push(builder.build());
  }

  // 매장 확정 실패 — 회색으로 눌러 둔다 (오류가 아니라 중간 상태다)
  ruleOn('outcome', '={REF}="needs_input"', '#f1f3f4', '#5f6368');
  // 폐업·휴업·오류 — 붉게
  ruleOn('outcome', '=OR({REF}="closed",{REF}="suspended",{REF}="error")', '#fce8e6', '#b3261e');
  // 동일업체 검증 실패 — Google 데이터가 버려진 행이라 근거가 약하다
  ruleOn('consistency', '=AND({REF}<>"",{REF}=FALSE)', '#fff3e0', null);

  sheet.setConditionalFormatRules(rules);
}

function protectHeader_(sheet, header) {
  sheet.getProtections(SpreadsheetApp.ProtectionType.RANGE).forEach(function (p) {
    if (p.getDescription() === 'Yielda header') p.remove();
  });
  sheet.getRange(1, 1, 1, header.length)
    .protect()
    .setDescription('Yielda header')
    .setWarningOnly(true);   // 완전 잠금이 아니라 경고 — 필요하면 넘어갈 수 있다
}

// ---------------------------------------------------------------------------
// 요약 탭 — QUERY 수식이라 원본이 늘어나면 자동으로 갱신된다
// ---------------------------------------------------------------------------
function buildSummary_() {
  var ss = SpreadsheetApp.getActiveSpreadsheet();
  var src = sheet_();
  var header = header_(src).filter(function (h) { return h !== ''; });
  if (header.length === 0) {
    throw new Error('데이터 탭(' + SHEET_NAME + ')에 헤더가 없습니다. 분석을 한 건 먼저 실행하세요.');
  }

  var sheet = ss.getSheetByName(SUMMARY_SHEET);
  if (sheet) sheet.clear();
  else sheet = ss.insertSheet(SUMMARY_SHEET);

  var lastCol = colLetter_(header.length);
  var body = "'" + SHEET_NAME + "'!A2:" + lastCol;

  function letterOf(name) {
    var i = header.indexOf(name);
    return i === -1 ? null : colLetter_(i + 1);
  }
  function countCol(name, title, limit) {
    var L = letterOf(name);
    if (!L) return ['(열 없음: ' + name + ')', ''];
    return [
      title,
      '=IFERROR(QUERY(' + body + ',"select ' + L + ', count(' + L + ') where ' + L +
      " is not null and " + L + " != '' group by " + L + ' order by count(' + L +
      ') desc limit ' + limit + ' label ' + L + " '" + title + "', count(" + L + ") '건수'\",0),\"—\")"
    ];
  }

  var tsCol = letterOf('timestamp');
  var outcomeCol = letterOf('outcome');
  var bizCol = letterOf('biz_no');

  var rows = [
    ['Yielda 분석 수집 — 요약', ''],
    ['이 탭은 수식이라 원본(' + SHEET_NAME + ')이 늘어나면 자동으로 갱신됩니다.', ''],
    ['', ''],
    ['총 분석 건수', '=COUNTA(' + "'" + SHEET_NAME + "'!" + (tsCol || 'A') + '2:' + (tsCol || 'A') + ')'],
    ['고유 사업자번호', bizCol
      ? '=COUNTA(UNIQUE(FILTER(' + "'" + SHEET_NAME + "'!" + bizCol + '2:' + bizCol +
        ',' + "'" + SHEET_NAME + "'!" + bizCol + '2:' + bizCol + '<>"")))'
      : '—'],
    ['성공 건수', outcomeCol
      ? '=COUNTIF(' + "'" + SHEET_NAME + "'!" + outcomeCol + '2:' + outcomeCol + ',"success")'
      : '—'],
    ['성공률', outcomeCol ? '=IFERROR(B6/B4,"—")' : '—'],
    ['', '']
  ];

  sheet.getRange(1, 1, rows.length, 2).setValues(rows);
  sheet.getRange(1, 1).setFontSize(14).setFontWeight('bold');
  sheet.getRange(2, 1).setFontColor('#5f6368');
  sheet.getRange(4, 1, 4, 1).setFontWeight('bold');
  sheet.getRange(7, 2).setNumberFormat('0.0%');

  // 분포표들 — 두 열씩 옆으로 배치한다.
  var blocks = [
    countCol('category', '업종', 12),
    countCol('district_type', '상권 유형', 12),
    countCol('outcome', '결과', 6),
    countCol('text_source', '분석 근거 출처', 6),
    countCol('client', '요청 출처', 6)
  ];

  var row = rows.length + 1;
  var col = 1;
  blocks.forEach(function (block, i) {
    sheet.getRange(row, col).setValue(block[0]).setFontWeight('bold');
    if (block[1]) sheet.getRange(row + 1, col).setFormula(block[1]);
    col += 3;                                  // 표 2열 + 여백 1열
    if ((i + 1) % 3 === 0) { row += 20; col = 1; }
  });

  // 일자별 건수 — timestamp 앞 10자가 날짜다 (ISO 문자열).
  if (tsCol) {
    var dayRow = row + 20;
    sheet.getRange(dayRow, 1).setValue('일자별 건수').setFontWeight('bold');
    sheet.getRange(dayRow + 1, 1).setFormula(
      '=IFERROR(QUERY(ARRAYFORMULA(LEFT(FILTER(' + "'" + SHEET_NAME + "'!" + tsCol + '2:' + tsCol +
      ',' + "'" + SHEET_NAME + "'!" + tsCol + '2:' + tsCol + '<>""),10)),' +
      '"select Col1, count(Col1) group by Col1 order by Col1 desc label Col1 \'날짜\', count(Col1) \'건수\'",0),"—")'
    );
  }

  sheet.setColumnWidth(1, 220);
  sheet.setColumnWidth(2, 110);
  sheet.setFrozenRows(2);
  return sheet;
}

// ---------------------------------------------------------------------------
// 시트 메뉴
// ---------------------------------------------------------------------------
function onOpen() {
  SpreadsheetApp.getUi()
    .createMenu('Yielda 수집')
    .addItem('표 서식 다시 적용', 'menuFormat')
    .addItem('요약 탭 만들기 / 새로고침', 'menuSummary')
    .addSeparator()
    .addItem('빈 탭·레거시 탭 정리', 'menuCleanup')
    .addToUi();
}

function menuFormat() {
  var sheet = sheet_();
  formatSheet_(sheet, header_(sheet).filter(function (h) { return h !== ''; }));
  SpreadsheetApp.getUi().alert('표 서식을 다시 적용했습니다.');
}

function menuSummary() {
  var ui = SpreadsheetApp.getUi();
  try {
    var sheet = buildSummary_();
    SpreadsheetApp.getActiveSpreadsheet().setActiveSheet(sheet);
    ui.alert('요약 탭을 갱신했습니다.');
  } catch (err) {
    ui.alert(String(err.message || err));
  }
}

/** 구 버전 스크립트가 남긴 탭(Sheet1 등)을 확인하고 지운다. */
function menuCleanup() {
  var ui = SpreadsheetApp.getUi();
  var ss = SpreadsheetApp.getActiveSpreadsheet();
  var stale = ss.getSheets().filter(function (s) {
    var name = s.getName();
    if (name === SHEET_NAME || name === SUMMARY_SHEET) return false;
    return s.getLastRow() === 0 || /^Sheet\d*$|^시트\d*$/.test(name);
  });

  if (stale.length === 0) {
    ui.alert('정리할 탭이 없습니다.');
    return;
  }

  var names = stale.map(function (s) {
    return '· ' + s.getName() + ' (' + s.getLastRow() + '행)';
  }).join('\n');
  var answer = ui.alert(
    '다음 탭을 삭제할까요?',
    names + '\n\n삭제하면 되돌릴 수 없습니다.',
    ui.ButtonSet.YES_NO
  );
  if (answer !== ui.Button.YES) return;

  stale.forEach(function (s) { ss.deleteSheet(s); });
  ui.alert(stale.length + '개 탭을 삭제했습니다.');
}

// ---------------------------------------------------------------------------
// 웹앱 엔드포인트
// ---------------------------------------------------------------------------
/** 분석 1건을 한 행으로 append. */
function doPost(e) {
  var lock = LockService.getScriptLock();
  try {
    lock.waitLock(20000);
  } catch (err) {
    return json_({ ok: false, error: 'busy' });
  }

  try {
    if (!e || !e.postData || !e.postData.contents) {
      return json_({ ok: false, error: 'empty body' });
    }

    var body = JSON.parse(e.postData.contents);
    if (!checkToken_(body.token)) {
      return json_({ ok: false, error: 'unauthorized' });
    }

    var row = body.row || {};
    var sheet = sheet_();
    var header = syncHeader_(sheet, body.columns || Object.keys(row));

    var values = header.map(function (key) {
      var v = row[key];
      if (v === null || v === undefined) return '';
      if (typeof v === 'boolean') return v ? 'TRUE' : 'FALSE';
      return v;
    });

    sheet.appendRow(values);
    return json_({ ok: true, row: sheet.getLastRow(), columns: header.length });
  } catch (err) {
    return json_({ ok: false, error: String(err) });
  } finally {
    lock.releaseLock();
  }
}

/** 최근 행을 최신순으로 돌려준다 (수집 대시보드용). */
function doGet(e) {
  var params = (e && e.parameter) || {};
  if (!checkToken_(params.token)) {
    return json_({ ok: false, error: 'unauthorized', columns: [], rows: [] });
  }

  var limit = Math.max(1, Math.min(parseInt(params.limit, 10) || 200, 5000));
  var sheet = sheet_();
  var lastRow = sheet.getLastRow();
  var lastCol = sheet.getLastColumn();

  if (lastRow < 2 || lastCol < 1) {
    return json_({ ok: true, columns: [], rows: [] });
  }

  var header = header_(sheet);
  var count = Math.min(limit, lastRow - 1);
  var startRow = lastRow - count + 1;           // 최신 count 건만 읽는다
  var values = sheet.getRange(startRow, 1, count, lastCol).getValues();

  var rows = values.map(function (line) {
    var obj = {};
    header.forEach(function (key, i) {
      if (!key) return;
      var v = line[i];
      if (v instanceof Date) v = v.toISOString();
      obj[key] = v;
    });
    return obj;
  }).reverse();                                  // 최신순

  return json_({ ok: true, columns: header.filter(String), rows: rows });
}
