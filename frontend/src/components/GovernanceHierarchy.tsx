import { useEffect, useRef, useState, useCallback, useMemo } from 'react';
import * as d3 from 'd3';
import { fetchJson } from '../api';
import { HierarchyNode, IssueKind, TaskStatus } from '../types';
import { useConsoleStore } from '../stores/console-store';
import { getStatusLabel } from '../utils/status-utils';

// --- Color constants ---
const STATUS_COLOR: Record<string, string> = {
  pending: '#94a3b8',
  ready: '#fbbf24',
  in_progress: '#f97316',
  verifying: '#a855f7',
  blocked: '#ef4444',
  done: '#22c55e',
};
const KIND_COLOR: Record<string, string> = {
  epic: '#3b82f6', story: '#10b981', task: '#6366f1',
  group: '#475569', root: '#0f172a',
};
const KIND_R: Record<string, number> = { epic: 18, story: 12, task: 8 };

// --- i18n ---
type LocaleKey = string;
type TranslationValue = string | ((args: Record<string, string | number>) => string) | LocaleKey;

const TRANSLATIONS: Record<string, Record<string, TranslationValue | Record<string, string>>> = {
  zh: {
    workspaceTitle: '治理执行拓扑',
    workspaceDescription: '左侧查看拓扑，右侧查看问题详情与执行信号。',
    workspaceEyebrow: '层级工作区',
    treeTip: '滚动缩放 · 拖动平移 · 点击节点查看详情',
    spinner: '正在加载治理树...',
    repoContextEyebrow: '当前上下文',
    repoHeadingEmpty: '选择一个仓库',
    metricRootLabel: '根节点范围',
    metricOrphanLabel: '游离分组',
    metricRootHint: '仓库根节点与治理分组',
    metricOrphanHint: '未挂在 Epic 主线下的 Story / Task',
    guideEyebrow: '使用说明',
    guideTitle: '如何查看这张图',
    guideItems: ['点击编号节点查看治理详情。', '根节点和游离分组仍可折叠展开。', '右侧面板用于快速确认关系和执行状态。'],
    legendEyebrow: '图例',
    legendTitle: '层级与状态标记',
    legendLabels: ['史诗', '故事', '任务', '待处理', '就绪', '阻塞', '进行中', '已完成'],
    detailEyebrow: '问题详情',
    detailPanelTitle: '治理详情面板',
    detailPanelHint: '选择编号节点后，这里会显示上下文、关系和执行状态。',
    drawerIdleTitle: '选择编号问题',
    drawerIdleBody: '保持树视图可见，并在这里查看当前问题的治理详情。',
    drawerIdleBullets: ['点击 Epic / Story / Task 节点加载详情。', '根节点和游离分组仍可折叠展开。', '若仓库已预填，页面打开后会自动加载。'],
    selectedIssue: '当前问题',
    detailIntro: '先确认治理链路，再决定是否进入其他执行工具。',
    lane: '泳道',
    complexity: '复杂度',
    executionStatus: '执行状态',
    workItemWave: '工作项 / 波次',
    notProjected: '未投影到 work_item',
    repositoryIssue: '仓库问题',
    openGithub: '打开 GitHub 问题',
    blockedBanner: (args) => `当前执行被阻塞：${args.reason}`,
    decisionBanner: '继续自动化前需要人工确认约束、优先级或范围。',
    description: '描述',
    parentLineage: '父级链路',
    governanceParent: '治理父级',
    relations: '关系',
    relationFallback: '关系',
    executionDiagnostics: '执行诊断',
    status: '状态',
    wave: '波次',
    workItemId: '工作项 ID',
    decisionGate: '决策门',
    needsOperatorDecision: '需要人工决策',
    orphanStories: '游离故事',
    orphanTasks: '游离任务',
    repoSummaryLoaded: (args) => `包含 ${args.epicCount} 个 Epic 根节点、${args.orphanStories} 个游离 Story、${args.orphanTasks} 个游离 Task。`,
    workspaceGuidanceWithOrphans: '存在游离分组，建议先核对治理挂载关系。',
    workspaceGuidanceClean: '没有游离分组，可直接沿 Epic 主线检查执行情况。',
    loadingIssue: (args) => `正在加载问题 #${args.number}...`,
    loadFailed: '加载失败',
    issueKinds: { epic: '史诗', story: '故事', task: '任务', group: '分组', root: '根节点', unknown: '未知' },
    taskTypes: { core_path: '核心路径', cross_cutting: '横切改动', documentation: '文档', governance: '治理' },
    reasonCodes: { waiting_for_retry: '等待重试', interrupted_retryable: '中断后可重试', credential_required: '需要凭证', tooling_error: '工具错误', protocol_error: '协议错误', timeout: '超时' },
    relationTypes: { blocked_by: '被阻塞于', blocks: '阻塞', depends_on: '依赖', parent: '父级', parent_candidate: '候选父级' },
  },
  en: {
    workspaceTitle: 'Governance Execution Topology',
    workspaceDescription: 'Use the left side for topology and the right side for issue diagnostics.',
    workspaceEyebrow: 'Hierarchy workspace',
    treeTip: 'Scroll to zoom · Drag to pan · Click a node for detail',
    spinner: 'Loading governance hierarchy...',
    repoContextEyebrow: 'Current context',
    repoHeadingEmpty: 'Select a repository',
    metricRootLabel: 'Root scope',
    metricOrphanLabel: 'Orphan groups',
    metricRootHint: 'Repository root and governance groups',
    metricOrphanHint: 'Stories / tasks outside epic lineage',
    guideEyebrow: 'Guide',
    guideTitle: 'How to read this view',
    guideItems: ['Click numbered nodes to inspect governance detail.', 'Root and orphan groups still collapse and expand.', 'Use the right panel to review relations and execution state.'],
    legendEyebrow: 'Legend',
    legendTitle: 'Hierarchy and status markers',
    legendLabels: ['Epic', 'Story', 'Task', 'Pending', 'Ready', 'Blocked', 'In progress', 'Done'],
    detailEyebrow: 'Issue diagnostics',
    detailPanelTitle: 'Governance detail panel',
    detailPanelHint: 'Select a numbered node to review context, relations, and runtime status here.',
    drawerIdleTitle: 'Select a numbered issue',
    drawerIdleBody: 'Keep the tree visible and use this panel to inspect the selected issue.',
    drawerIdleBullets: ['Click epic, story, or task nodes to load detail.', 'Root and orphan groups still collapse and expand.', 'Prefilled repositories auto-load on open.'],
    selectedIssue: 'Selected issue',
    detailIntro: 'Review governance lineage before jumping into execution tooling.',
    lane: 'Lane',
    complexity: 'Complexity',
    executionStatus: 'Execution status',
    workItemWave: 'Work item / Wave',
    notProjected: 'Not projected to work_item',
    repositoryIssue: 'Repository issue',
    openGithub: 'Open GitHub Issue',
    blockedBanner: (args) => `Execution is blocked: ${args.reason}`,
    decisionBanner: 'Operator review is required before automation continues.',
    description: 'Description',
    parentLineage: 'Parent lineage',
    governanceParent: 'Governance parent',
    relations: 'Relations',
    relationFallback: 'relation',
    executionDiagnostics: 'Execution diagnostics',
    status: 'Status',
    wave: 'Wave',
    workItemId: 'Work item ID',
    decisionGate: 'Decision gate',
    needsOperatorDecision: 'Needs operator decision',
    orphanStories: 'Orphan Stories',
    orphanTasks: 'Orphan Tasks',
    repoSummaryLoaded: (args) => `${args.epicCount} epic roots, ${args.orphanStories} orphan stories, ${args.orphanTasks} orphan tasks.`,
    workspaceGuidanceWithOrphans: 'Orphan groups detected — check governance links first.',
    workspaceGuidanceClean: 'No orphan groups. Review epic lineage directly.',
    loadingIssue: (args) => `Loading issue #${args.number}...`,
    loadFailed: 'Load failed',
    issueKinds: { epic: 'Epic', story: 'Story', task: 'Task', group: 'Group', root: 'Root', unknown: 'Unknown' },
    taskTypes: { core_path: 'Core Path', cross_cutting: 'Cross-cutting', documentation: 'Documentation', governance: 'Governance' },
    reasonCodes: { waiting_for_retry: 'Waiting for Retry', interrupted_retryable: 'Interrupted, Retryable', credential_required: 'Credential Required', tooling_error: 'Tooling Error', protocol_error: 'Protocol Error', timeout: 'Timeout' },
    relationTypes: { blocked_by: 'Blocked by', blocks: 'Blocks', depends_on: 'Depends on', parent: 'Parent', parent_candidate: 'Parent Candidate' },
  },
};

function t(locale: string, path: string, args?: Record<string, string | number>): string {
  const parts = path.split('.');
  let current: unknown = TRANSLATIONS[locale] || TRANSLATIONS['zh'];
  for (const part of parts) {
    if (current && typeof current === 'object') {
      current = (current as Record<string, unknown>)[part];
    } else {
      return path;
    }
  }
  if (typeof current === 'function') return current(args || {});
  return typeof current === 'string' ? current : path;
}

function localizeKind(locale: string, kind: IssueKind | string): string {
  const kinds = (TRANSLATIONS[locale] || TRANSLATIONS['zh']).issueKinds as Record<string, string>;
  return kinds[kind] || kind;
}

function localizeStatus(locale: string, status: TaskStatus | string): string {
  if (status && ['pending', 'ready', 'in_progress', 'verifying', 'blocked', 'done'].includes(status)) {
    return getStatusLabel(status as TaskStatus);
  }
  return status || '—';
}

function localizeTaskType(locale: string, taskType: string): string {
  const types = (TRANSLATIONS[locale] || TRANSLATIONS['zh']).taskTypes as Record<string, string>;
  return types[taskType] || taskType;
}

function localizeReason(locale: string, reason: string): string {
  const codes = (TRANSLATIONS[locale] || TRANSLATIONS['zh']).reasonCodes as Record<string, string>;
  return codes[reason] || reason.replace(/[_-]+/g, ' ').replace(/\b\w/g, c => c.toUpperCase());
}

function localizeRelationType(locale: string, relType: string): string {
  const types = (TRANSLATIONS[locale] || TRANSLATIONS['zh']).relationTypes as Record<string, string>;
  return types[relType] || relType;
}

// --- Tree node data shape ---
interface TreeNodeData {
  issue_number: number;
  title: string;
  issue_kind: string;
  github_state?: string;
  status_label?: string;
  url?: string;
  lane?: string;
  complexity?: number;
  work_status?: TaskStatus;
  blocked_reason?: string;
  decision_required?: boolean;
  body?: string;
  parents?: number[];
  relations?: Array<{ dir: string; number: number; type: string }>;
  children?: TreeNodeData[];
  _collapsed?: boolean;
}

// --- Issue detail shape from API ---
interface IssueDetail {
  issue_number: number;
  title: string;
  issue_kind: IssueKind;
  github_state?: string;
  url?: string;
  lane?: string;
  complexity?: number;
  body?: string;
  work_item?: {
    status: TaskStatus;
    wave?: string;
    id?: string;
    task_type?: string;
    blocked_reason?: string;
    decision_required?: boolean;
  };
  parents?: number[];
  relations?: Array<{ dir: string; number: number; type: string }>;
}

interface HierarchyStats {
  epicCount: number;
  orphanStories: number;
  orphanTasks: number;
}

export default function GovernanceHierarchy() {
  const store = useConsoleStore();
  const repo = store.repo;
  const locale = store.locale;

  const treeContainerRef = useRef<HTMLDivElement>(null);
  const [treeStats, setTreeStats] = useState<HierarchyStats | null>(null);
  const [selectedDetail, setSelectedDetail] = useState<IssueDetail | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [statusMsg, setStatusMsg] = useState<string>('');
  const [statusTone, setStatusTone] = useState<'idle' | 'loading' | 'ready' | 'error'>('idle');
  const [treeData, setTreeData] = useState<{ epics: TreeNodeData[]; orphan_stories: TreeNodeData[]; orphan_tasks: TreeNodeData[] } | null>(null);

  // --- D3 tree builder ---
  const buildTree = useCallback((data: { epics: TreeNodeData[]; orphan_stories: TreeNodeData[]; orphan_tasks: TreeNodeData[] }, currentRepo: string) => {
    const container = treeContainerRef.current;
    if (!container) return;

    // Clear previous
    container.innerHTML = '';

    const rootData: TreeNodeData = {
      issue_number: 0,
      title: currentRepo,
      issue_kind: 'root',
      children: [
        ...data.epics,
        ...(data.orphan_stories.length ? [{
          issue_number: -1,
          title: t(locale, 'orphanStories'),
          issue_kind: 'group',
          children: data.orphan_stories,
        }] : []),
        ...(data.orphan_tasks.length ? [{
          issue_number: -2,
          title: t(locale, 'orphanTasks'),
          issue_kind: 'group',
          children: data.orphan_tasks,
        }] : []),
      ],
    };

    const W = container.clientWidth;
    const H = container.clientHeight || 520;
    const margin = { top: 40, right: 220, bottom: 40, left: 96 };
    const w = W - margin.left - margin.right;
    const h = H - margin.top - margin.bottom;

    const svg = d3.select(container).append('svg')
      .attr('width', W)
      .attr('height', H);
    const g = svg.append('g').attr('transform', `translate(${margin.left},${margin.top})`);

    svg.call(d3.zoom<SVGSVGElement, unknown>().scaleExtent([0.1, 4]).on('zoom', (event) => {
      g.attr('transform', event.transform);
    }));

    const root = d3.hierarchy(rootData, (d) => (d as TreeNodeData)._collapsed ? undefined : (d as TreeNodeData).children);
    root.x0 = h / 2;
    root.y0 = 0;

    const treeLayout = d3.tree<{ children?: TreeNodeData[] }>().size([h, w]);

    function update(source: d3.HierarchyNode<TreeNodeData>) {
      treeLayout(root as unknown as d3.HierarchyNode<{ children?: TreeNodeData[] }>);
      const nodes = root.descendants();
      const links = root.links();

      nodes.forEach((d) => { d.y = d.depth * 220; });

      // Links
      const link = g.selectAll('.link').data(links, (d) => (d.target.data as TreeNodeData).issue_number);
      link.enter().append('path').attr('class', 'link')
        .attr('d', d3.linkHorizontal<d3.HierarchyLink<TreeNodeData>, d3.HierarchyPointNode<TreeNodeData>>().x((d) => d.y).y((d) => d.x) as any)
        .merge(link as any)
        .transition().duration(300)
        .attr('d', d3.linkHorizontal().x((d: any) => d.y).y((d: any) => d.x) as any);
      link.exit().remove();

      // Nodes
      const node = g.selectAll('.node').data(nodes, (d) => (d.data as TreeNodeData).issue_number);
      const nodeEnter = node.enter().append('g').attr('class', 'node')
        .attr('transform', `translate(${source.y0},${source.x0})`);

      nodeEnter.append('circle')
        .attr('r', (d) => KIND_R[(d.data as TreeNodeData).issue_kind] || 7)
        .attr('fill', (d) => {
          const ws = (d.data as TreeNodeData).work_status;
          return ws && STATUS_COLOR[ws] ? STATUS_COLOR[ws] : KIND_COLOR[(d.data as TreeNodeData).issue_kind] || '#94a3b8';
        })
        .attr('stroke', (d) => {
          const color = (() => {
            const ws = (d.data as TreeNodeData).work_status;
            return ws && STATUS_COLOR[ws] ? STATUS_COLOR[ws] : KIND_COLOR[(d.data as TreeNodeData).issue_kind] || '#94a3b8';
          })();
          return d3.color(color)?.darker(0.8)?.toString() || color;
        })
        .attr('stroke-width', 2)
        .style('cursor', 'pointer')
        .on('click', (event: MouseEvent, d: d3.HierarchyNode<TreeNodeData>) => {
          event.stopPropagation();
          const data = d.data as TreeNodeData;
          if (data.issue_kind === 'root' || data.issue_kind === 'group') {
            data._collapsed = !data._collapsed;
            update(d);
            return;
          }
          void loadDetailFromTree(data.issue_number);
        });

      nodeEnter.append('text')
        .attr('dy', '0.32em')
        .attr('x', (d) => (KIND_R[(d.data as TreeNodeData).issue_kind] || 7) + 7)
        .attr('text-anchor', 'start')
        .text((d) => {
          const data = d.data as TreeNodeData;
          if (data.issue_kind === 'root') return '';
          if (data.issue_kind === 'group') return data.title;
          const label = data.issue_number > 0 ? `#${data.issue_number} ` : '';
          const title = data.title || '';
          return label + (title.length > 34 ? `${title.slice(0, 34)}…` : title);
        })
        .style('font-size', '12px')
        .style('cursor', 'pointer')
        .style('fill', '#0f172a')
        .style('user-select', 'none')
        .on('click', (event: MouseEvent, d: d3.HierarchyNode<TreeNodeData>) => {
          event.stopPropagation();
          const data = d.data as TreeNodeData;
          if (data.issue_number > 0) void loadDetailFromTree(data.issue_number);
        });

      const nodeUpdate = nodeEnter.merge(node);
      nodeUpdate.transition().duration(300)
        .attr('transform', (d) => `translate(${d.y},${d.x})`);

      node.exit().transition().duration(200)
        .attr('transform', `translate(${source.y},${source.x})`)
        .remove();

      nodes.forEach((d) => { d.x0 = d.x; d.y0 = d.y; });
    }

    update(root);
  }, [locale]);

  // --- Load hierarchy ---
  const loadHierarchy = useCallback(async () => {
    if (!repo) return;
    setStatusMsg(t(locale, 'spinner'));
    setStatusTone('loading');
    try {
      const data = await fetchJson<{ epics: TreeNodeData[]; orphan_stories: TreeNodeData[]; orphan_tasks: TreeNodeData[] }>(
        `/api/hierarchy?repo=${encodeURIComponent(repo)}`
      );
      setTreeData(data);
      const stats: HierarchyStats = {
        epicCount: data.epics?.length || 0,
        orphanStories: data.orphan_stories?.length || 0,
        orphanTasks: data.orphan_tasks?.length || 0,
      };
      setTreeStats(stats);
      buildTree(data, repo);
      setStatusMsg(t(locale, 'repoSummaryLoaded', stats));
      setStatusTone('ready');
    } catch (err) {
      setStatusMsg(`${t(locale, 'loadFailed')}: ${err instanceof Error ? err.message : String(err)}`);
      setStatusTone('error');
    }
  }, [repo, locale, buildTree]);

  // --- Load issue detail ---
  const loadDetailFromTree = useCallback(async (issueNumber: number) => {
    if (!repo) return;
    setDetailLoading(true);
    try {
      const detail = await fetchJson<IssueDetail>(
        `/api/issue/${issueNumber}?repo=${encodeURIComponent(repo)}`
      );
      setSelectedDetail(detail);
    } catch {
      setSelectedDetail(null);
    } finally {
      setDetailLoading(false);
    }
  }, [repo]);

  // Auto-load when repo changes
  useEffect(() => {
    if (repo) void loadHierarchy();
  }, [repo, loadHierarchy]);

  // --- Legend entries ---
  const legendColors = ['#3b82f6', '#10b981', '#6366f1', '#94a3b8', '#fbbf24', '#ef4444', '#f97316', '#22c55e'];
  const legendLabels = (TRANSLATIONS[locale] || TRANSLATIONS['zh']).legendLabels as string[];

  // --- Guidance text ---
  const guidanceText = useMemo(() => {
    if (!treeStats) return t(locale, 'workspaceGuidanceClean');
    return (treeStats.orphanStories + treeStats.orphanTasks) > 0
      ? t(locale, 'workspaceGuidanceWithOrphans')
      : t(locale, 'workspaceGuidanceClean');
  }, [treeStats, locale]);

  // --- Idle bullets ---
  const idleBullets = (TRANSLATIONS[locale] || TRANSLATIONS['zh']).drawerIdleBullets as string[];
  const guideItems = (TRANSLATIONS[locale] || TRANSLATIONS['zh']).guideItems as string[];

  return (
    <section className="flex h-full">
      <div className="flex flex-1 gap-4 overflow-hidden p-4">
        {/* Main workspace */}
        <div className="flex flex-1 flex-col gap-4 min-w-0 overflow-auto">
          {/* Summary cards */}
          <div className="grid gap-4 lg:grid-cols-3">
            {/* Context card */}
            <div className="rounded-xl border border-border bg-surface p-4">
              <p className="text-xs uppercase tracking-wide text-primary font-bold">{t(locale, 'repoContextEyebrow')}</p>
              <h2 className="text-lg font-semibold text-text">{treeStats ? repo : t(locale, 'repoHeadingEmpty')}</h2>
              <p className="text-sm text-text-secondary">
                {treeStats ? t(locale, 'repoSummaryLoaded', treeStats) : t(locale, 'repoHeadingEmpty')}
              </p>
              <div className="mt-3 grid grid-cols-2 gap-2">
                <div className="rounded-lg border border-border bg-surface-hover p-3">
                  <span className="block text-xs uppercase tracking-wide text-text-secondary font-bold">{t(locale, 'metricRootLabel')}</span>
                  <span className="block text-xl font-bold text-text">{treeStats?.epicCount ?? '—'}</span>
                  <span className="text-xs text-text-secondary">{t(locale, 'metricRootHint')}</span>
                </div>
                <div className="rounded-lg border border-border bg-surface-hover p-3">
                  <span className="block text-xs uppercase tracking-wide text-text-secondary font-bold">{t(locale, 'metricOrphanLabel')}</span>
                  <span className="block text-xl font-bold text-text">{treeStats ? treeStats.orphanStories + treeStats.orphanTasks : '—'}</span>
                  <span className="text-xs text-text-secondary">{t(locale, 'metricOrphanHint')}</span>
                </div>
              </div>
            </div>

            {/* Guide card */}
            <div className="rounded-xl border border-border bg-surface p-4">
              <p className="text-xs uppercase tracking-wide text-text-secondary font-bold">{t(locale, 'guideEyebrow')}</p>
              <h3 className="text-sm font-semibold text-text">{t(locale, 'guideTitle')}</h3>
              <ul className="mt-2 space-y-1">
                {guideItems.map((item, i) => (
                  <li key={i} className="text-sm text-text-secondary">• {item}</li>
                ))}
              </ul>
            </div>

            {/* Legend card */}
            <div className="rounded-xl border border-border bg-surface p-4">
              <p className="text-xs uppercase tracking-wide text-text-secondary font-bold">{t(locale, 'legendEyebrow')}</p>
              <h3 className="text-sm font-semibold text-text">{t(locale, 'legendTitle')}</h3>
              <div className="mt-2 grid grid-cols-2 gap-2">
                {legendColors.map((color, i) => (
                  <div key={i} className="inline-flex items-center gap-2 rounded-full border border-border bg-surface px-2 py-1 text-xs">
                    <span className="inline-block h-2.5 w-2.5 shrink-0 rounded-full" style={{ backgroundColor: color }} />
                    <span className="text-text-secondary">{legendLabels[i]}</span>
                  </div>
                ))}
              </div>
            </div>
          </div>

          {/* Tree panel */}
          <div className="flex flex-1 flex-col rounded-xl border border-border bg-surface overflow-hidden min-h-[520px]">
            <div className="flex items-start justify-between gap-4 border-b border-border px-5 py-4">
              <div>
                <p className="text-xs uppercase tracking-wide text-text-secondary font-bold">{t(locale, 'workspaceEyebrow')}</p>
                <h2 className="text-lg font-semibold text-text">{t(locale, 'workspaceTitle')}</h2>
                <p className="text-sm text-text-secondary">{t(locale, 'workspaceDescription')}</p>
              </div>
              <div className="flex flex-wrap gap-2">
                <span className="inline-flex items-center gap-1.5 rounded-full border border-border bg-surface px-2 py-1 text-xs text-text-secondary">
                  {repo ? `Repo: ${repo}` : 'Repo: —'}
                </span>
                <span className={`inline-flex items-center gap-1.5 rounded-full border px-2 py-1 text-xs ${
                  statusTone === 'loading' ? 'border-blue-300 bg-blue-50 text-blue-700' :
                  statusTone === 'error' ? 'border-red-300 bg-red-50 text-red-700' :
                  statusTone === 'ready' ? 'border-green-300 bg-green-50 text-green-700' :
                  'border-border bg-surface text-text-secondary'
                }`}>
                  <span className="inline-block h-2 w-2 rounded-full" style={{
                    backgroundColor: statusTone === 'loading' ? '#3b82f6' : statusTone === 'error' ? '#ef4444' : statusTone === 'ready' ? '#22c55e' : '#94a3b8',
                  }} />
                  {statusMsg || t(locale, 'repoHeadingEmpty')}
                </span>
              </div>
            </div>

            {/* D3 tree area */}
            <div className="relative flex-1 min-h-[520px] overflow-hidden"
              style={{
                background: 'linear-gradient(180deg, rgba(255,255,255,0.6), rgba(248,250,252,0.95)), linear-gradient(90deg, rgba(148,163,184,0.08) 1px, transparent 1px), linear-gradient(rgba(148,163,184,0.08) 1px, transparent 1px)',
                backgroundSize: 'auto, 32px 32px, 32px 32px',
              }}
            >
              {statusTone === 'loading' && (
                <div className="absolute left-1/2 top-1/2 z-10 flex -translate-x-1/2 -translate-y-1/2 items-center gap-2 rounded-full bg-slate-900/88 px-4 py-2 text-sm text-slate-200 shadow-lg">
                  <div className="h-3 w-3 animate-spin rounded-full border-2 border-white/25 border-t-sky-400" />
                  {t(locale, 'spinner')}
                </div>
              )}
              {/* Overlay cards */}
              <div className="absolute inset-x-4 top-4 z-10 flex items-start justify-between gap-3 pointer-events-none">
                <div className="max-w-xs rounded-xl border border-border bg-white/88 backdrop-blur-sm p-3 shadow-md pointer-events-auto">
                  <h3 className="text-xs uppercase tracking-wide text-text-secondary font-bold">{t(locale, 'guideTitle')}</h3>
                  <p className="mt-1 text-sm text-text-secondary">{guidanceText}</p>
                </div>
                <div className="rounded-xl border border-slate-700 bg-slate-900 px-3 py-2 text-xs font-semibold text-slate-200 shadow-lg pointer-events-auto">
                  {t(locale, 'treeTip')}
                </div>
              </div>
              <div ref={treeContainerRef} className="h-full w-full" />
            </div>
          </div>
        </div>

        {/* Detail panel */}
        <div className="flex w-96 shrink-0 flex-col rounded-xl border border-border bg-surface overflow-hidden">
          <div className="flex items-start justify-between gap-3 border-b border-border px-5 py-4">
            <div>
              <p className="text-xs uppercase tracking-wide text-text-secondary font-bold">{t(locale, 'detailEyebrow')}</p>
              <h2 className="text-lg font-semibold text-text">{t(locale, 'detailPanelTitle')}</h2>
              <p className="text-sm text-text-secondary">{t(locale, 'detailPanelHint')}</p>
            </div>
            <button
              type="button"
              onClick={() => { setSelectedDetail(null); }}
              className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg border border-border bg-surface-hover text-text-secondary hover:bg-surface hover:text-text"
              aria-label="Close"
            >
              ×
            </button>
          </div>
          <div className="flex-1 overflow-auto p-5">
            {detailLoading ? (
              <div className="flex items-center justify-center gap-2 text-sm text-text-secondary">
                <div className="h-3 w-3 animate-spin rounded-full border-2 border-primary/25 border-t-primary" />
                {t(locale, 'spinner')}
              </div>
            ) : selectedDetail ? (
              <DetailContent detail={selectedDetail} locale={locale} />
            ) : (
              <div className="flex flex-col gap-3 rounded-xl border border-dashed border-border bg-surface p-6">
                <h3 className="text-lg font-semibold text-text">{t(locale, 'drawerIdleTitle')}</h3>
                <p className="text-sm text-text-secondary">{t(locale, 'drawerIdleBody')}</p>
                <ul className="space-y-1">
                  {idleBullets.map((item, i) => (
                    <li key={i} className="text-sm text-text-secondary">• {item}</li>
                  ))}
                </ul>
              </div>
            )}
          </div>
        </div>
      </div>
    </section>
  );
}

// --- Detail content sub-component ---
function DetailContent({ detail, locale }: { detail: IssueDetail; locale: string }) {
  const kindColors: Record<string, string> = { epic: '#3b82f6', story: '#10b981', task: '#6366f1' };
  const kc = kindColors[detail.issue_kind] || '#94a3b8';
  const workItem = detail.work_item;

  return (
    <div className="space-y-4">
      {/* Title block */}
      <div>
        <p className="text-xs uppercase tracking-wide text-text-secondary">{t(locale, 'selectedIssue')}</p>
        <h3 className="text-lg font-semibold text-text">#{detail.issue_number} {detail.title || ''}</h3>
        <p className="text-sm text-text-secondary">{t(locale, 'detailIntro')}</p>
      </div>

      {/* Badges */}
      <div className="flex flex-wrap gap-2">
        <span className="rounded-full border border-border px-2 py-0.5 text-xs font-semibold" style={{ backgroundColor: `${kc}20`, color: kc }}>
          {localizeKind(locale, detail.issue_kind)}
        </span>
        {detail.github_state && (
          <span className="rounded-full border border-border bg-surface-hover px-2 py-0.5 text-xs text-text-secondary">
            {detail.github_state}
          </span>
        )}
        {workItem?.status && (
          <span className={`badge badge-${workItem.status}`}>
            {localizeStatus(locale, workItem.status)}
          </span>
        )}
      </div>

      {/* Meta grid */}
      <div className="grid grid-cols-2 gap-2">
        {[
          { label: t(locale, 'lane'), value: detail.lane || '—' },
          { label: t(locale, 'complexity'), value: String(detail.complexity ?? '—') },
          { label: t(locale, 'executionStatus'), value: workItem ? localizeStatus(locale, workItem.status) : t(locale, 'notProjected') },
          { label: t(locale, 'workItemWave'), value: `${workItem?.id || '—'} · ${workItem?.wave || '—'}` },
        ].map(({ label, value }) => (
          <div key={label} className="rounded-lg border border-border bg-surface-hover p-3">
            <span className="block text-xs uppercase tracking-wide text-text-secondary font-bold">{label}</span>
            <span className="block text-sm font-semibold text-text">{value}</span>
          </div>
        ))}
      </div>

      {/* Blocked/Decision banners */}
      {workItem?.blocked_reason && (
        <div className="rounded-lg border border-red-200 bg-red-50 p-3 text-sm font-semibold text-red-700">
          {t(locale, 'blockedBanner', { reason: workItem.blocked_reason })}
        </div>
      )}
      {workItem?.decision_required && (
        <div className="rounded-lg border border-orange-200 bg-orange-50 p-3 text-sm font-semibold text-orange-700">
          {t(locale, 'decisionBanner')}
        </div>
      )}

      {/* Body */}
      {detail.body && (
        <div className="rounded-lg border border-border overflow-hidden">
          <div className="border-b border-border bg-surface-hover px-4 py-2">
            <h4 className="text-xs uppercase tracking-wide text-text-secondary font-bold">{t(locale, 'description')}</h4>
          </div>
          <div className="max-h-80 overflow-auto whitespace-pre-wrap break-words bg-background p-3 text-sm text-text-secondary">
            {detail.body}
          </div>
        </div>
      )}

      {/* Parents */}
      {detail.parents && detail.parents.length > 0 && (
        <div className="rounded-lg border border-border overflow-hidden">
          <div className="border-b border-border bg-surface-hover px-4 py-2">
            <h4 className="text-xs uppercase tracking-wide text-text-secondary font-bold">{t(locale, 'parentLineage')}</h4>
          </div>
          <div className="p-3 space-y-2">
            {detail.parents.map((parent) => (
              <div key={parent} className="flex items-center justify-between rounded-lg border border-border bg-background px-3 py-2 text-sm">
                <span className="font-semibold text-text">#{parent}</span>
                <span className="text-xs text-text-secondary">{t(locale, 'governanceParent')}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Relations */}
      {detail.relations && detail.relations.length > 0 && (
        <div className="rounded-lg border border-border overflow-hidden">
          <div className="border-b border-border bg-surface-hover px-4 py-2">
            <h4 className="text-xs uppercase tracking-wide text-text-secondary font-bold">{t(locale, 'relations')}</h4>
          </div>
          <div className="p-3 space-y-2">
            {detail.relations.map((rel, i) => (
              <div key={i} className="flex items-center justify-between rounded-lg border border-border bg-background px-3 py-2 text-sm">
                <span className="font-semibold text-text">{rel.dir === 'outgoing' ? '→' : '←'} #{rel.number}</span>
                <span className="text-xs text-text-secondary">{rel.type ? localizeRelationType(locale, rel.type) : t(locale, 'relationFallback')}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* GitHub link */}
      {detail.url && (
        <div className="rounded-lg border border-border overflow-hidden">
          <div className="border-b border-border bg-surface-hover px-4 py-2">
            <h4 className="text-xs uppercase tracking-wide text-text-secondary font-bold">{t(locale, 'repositoryIssue')}</h4>
          </div>
          <div className="p-3">
            <a href={detail.url} target="_blank" rel="noopener noreferrer" className="text-sm font-semibold text-primary hover:underline">
              ↗ {t(locale, 'openGithub')}
            </a>
          </div>
        </div>
      )}

      {/* Execution diagnostics */}
      {workItem && (
        <div className="rounded-lg border border-border overflow-hidden">
          <div className="border-b border-border bg-surface-hover px-4 py-2">
            <h4 className="text-xs uppercase tracking-wide text-text-secondary font-bold">{t(locale, 'executionDiagnostics')}</h4>
          </div>
          <div className="p-3 space-y-2">
            {[
              { label: t(locale, 'status'), value: localizeStatus(locale, workItem.status) },
              { label: t(locale, 'wave'), value: workItem.wave || '—' },
              { label: t(locale, 'workItemId'), value: workItem.id || '—' },
              ...(workItem.task_type ? [{ label: locale === 'zh' ? '任务类型' : 'Task Type', value: localizeTaskType(locale, workItem.task_type) }] : []),
              ...(workItem.blocked_reason ? [{ label: locale === 'zh' ? '阻塞原因' : 'Blocked Reason', value: localizeReason(locale, workItem.blocked_reason) }] : []),
              ...(workItem.decision_required ? [{ label: t(locale, 'decisionGate'), value: t(locale, 'needsOperatorDecision') }] : []),
            ].map(({ label, value }) => (
              <div key={label} className="flex items-center justify-between rounded-lg border border-border bg-background px-3 py-2 text-sm">
                <span className="font-semibold text-text">{label}</span>
                <span className="text-xs text-text-secondary">{value}</span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
