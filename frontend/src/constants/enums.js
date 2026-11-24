export const Role = Object.freeze({ VIEWER: 'viewer', ANALYST: 'analyst', SUPERVISOR: 'supervisor' });
export const RunStatus = Object.freeze({ QUEUED: 'queued', SUCCEEDED: 'succeeded', FAILED: 'failed' });
export const Decision = Object.freeze({ APPROVED: 'approved', RETURNED: 'returned' });
export const QueueStatus = Object.freeze({ QUEUED: 'queued', COMPUTING: 'computing', READY: 'ready', ACTIVE: 'active', FAILED: 'failed', SUPERSEDED: 'superseded' });
export const SignoffOutcome = Object.freeze({ POSITIVE: '返染', NEGATIVE: '留样', WITHDRAWN: '撤回' });
export const roleName = {viewer: '只读查看', analyst: '业务分析员', supervisor: '复核负责人'};
export const statusName = {queued: '等待计算', succeeded: '等待复核', failed: '计算失败', approved: '已签核', returned: '已退回'};
export const queueStatusName = {
  queued: '排队等待', computing: '计算中', ready: '算齐待切换', active: '已生效',
  failed: '计算失败', superseded: '已被新版取代',
};
