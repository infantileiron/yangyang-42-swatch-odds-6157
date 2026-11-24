import { download, get, post } from '../api/client.js';
import { intro } from '../components/common/frame.js';
import { table } from '../components/common/data.js';
import { formError } from '../components/common/forms.js';
import { QueueStatus, Role, SignoffOutcome, queueStatusName } from '../constants/enums.js';
import { bindDownloads, bindForm, notify } from '../hooks/actions.js';
import { esc, timeLabel } from '../utils/html.js';

const outcomeTag = row => {
  const tone = row.outcome === SignoffOutcome.POSITIVE ? 'positive'
    : row.outcome === SignoffOutcome.NEGATIVE ? 'negative' : 'pending';
  return `<span class="tag tag-${tone}">${esc(row.outcome)}</span>`;
};

function queueCard(item, fallback) {
  if (!item) return `<div class="panel-body muted">${esc(fallback)}</div>`;
  const tone = item.status === QueueStatus.ACTIVE ? 'status-approved'
    : item.status === QueueStatus.FAILED ? 'status-returned' : 'status-queued';
  const pct = item.total ? Math.round((item.computed / item.total) * 100) : 0;
  const running = item.status === QueueStatus.QUEUED || item.status === QueueStatus.COMPUTING;
  return `<div class="panel-body queue-card"><div class="queue-head"><b>队列 r${item.revision}</b>
    <span class="status ${tone}">${esc(queueStatusName[item.status] || item.status)}</span></div>
    <dl class="metrics"><div><dt>待判色卡</dt><dd>${item.total}<small> 张</small></dd></div>
    <div><dt>已算</dt><dd>${item.computed}<small> 张</small></dd></div>
    <div><dt>暂停下发</dt><dd>${item.held_tickets.length}<small> 张</small></dd></div></dl>
    ${running ? `<div class="progress" aria-label="计算进度"><i style="--width:${pct}%"></i><span>${pct}%</span></div>` : ''}
    ${item.held_tickets.length ? `<p class="aside-note">暂停下发：${esc(item.held_tickets.join('、'))}</p>` : ''}
    ${item.reason ? `<p class="aside-note">${esc(item.reason)}</p>` : ''}
    <p class="aside-note">更新于 ${timeLabel(item.activated_at || item.ready_at || item.created_at)}</p></div>`;
}

export async function signoffPage(spec, user) {
  const [overview, signoffs] = await Promise.all([get('/queues'), get('/signoffs')]);
  const supervisor = user.role === Role.SUPERVISOR;
  const incoming = overview.incoming;
  const banner = incoming && incoming.revision > (overview.active?.revision || 0)
    ? `<div class="banner" role="status">新版队列 r${incoming.revision} 正在重算：旧队列 r${overview.active?.revision ?? '—'} 仍可查询下载，受影响色卡先暂停下发，算齐后一次性切换。</div>` : '';
  const form = supervisor ? `<form id="signoff-form" class="panel-body">
      <label class="field"><span>色样号</span><input name="ticket" required maxlength="120" placeholder="CY-P05"></label>
      <div class="form-grid"><label class="field"><span>签认版本</span><input name="version" type="number" min="1" required value="1"></label>
      <label class="field"><span>返染签认</span><select name="outcome" required>
        <option value="${SignoffOutcome.POSITIVE}">返染</option><option value="${SignoffOutcome.NEGATIVE}">留样</option>
        <option value="${SignoffOutcome.WITHDRAWN}">撤回（回到待判）</option></select></label></div>
      <label class="field"><span>补录备注</span><input name="note" maxlength="500" placeholder="来源与说明"></label>
      ${formError}<button class="primary">保存补录</button>
      <p class="aside-note">乱序到达时以最高版本为准；撤回后该色卡回到待判。有效签认变更会自动重算受影响的抽查队列。</p></form>`
    : '<p class="panel-body">由复核负责人补录返染签认。此账号可查看有效签认与队列状态。</p>';
  return `${intro('签认与抽查队列', '补录返染签认驱动队列重算，同张色卡以最高版本为准。', '<button data-download="/queues/active/export">下载当前队列 CSV</button>')}
    ${banner}
    <div class="split"><section class="panel"><div class="panel-heading"><h2>补录签认</h2></div>${form}</section>
    <aside class="method"><h2>生效队列</h2>${queueCard(overview.active, '暂无生效队列。')}
    <h2>重算待切换</h2>${queueCard(incoming, '暂无待切换队列。')}</aside></div>
    <section class="panel"><div class="panel-heading"><h2>有效签认</h2></div>
    ${table([{key:'ticket',label:'色样号'},{label:'签认',html:outcomeTag},{label:'版本',html:row => `v${row.version}`},
      {key:'note',label:'备注'},{key:'actor',label:'补录人'},{label:'时间',html:row => timeLabel(row.received_at)}],
      signoffs, '还没有签认补录。')}</section>`;
}

export function wireSignoffs(root, refresh) {
  bindDownloads(root, download);
  bindForm(root.querySelector('#signoff-form'), async form => {
    const values = Object.fromEntries(new FormData(form));
    const report = await post('/signoffs', {items: [{ticket: values.ticket.trim(), version: Number(values.version),
      outcome: values.outcome, note: values.note || ''}]});
    if (report.changes?.length) {
      const change = report.changes[0];
      notify(`签认已更新：${change.ticket} ${change.from} → ${change.to}，已登记队列重算`);
    } else {
      notify(report.accepted ? '签认已归档（未改变有效值）' : '已存在相同签认，未重复写入');
    }
    refresh();
  });
}
