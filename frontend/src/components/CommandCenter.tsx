import { useMemo, useState } from 'react';
import { CheckCircle2, HelpCircle, Layers3, Send } from 'lucide-react';
import { IntakeIntent, SystemStatus } from '../types';
import { Button } from './Button';

interface CommandCenterProps {
  intents: IntakeIntent[];
  selectedIntentId: string | null;
  isSubmitting: boolean;
  systemStatus: SystemStatus | null;
  onSendCommand: (command: string) => void;
  onSelectIntent: (intentId: string | null) => void;
  onApproveSelectedIntent: () => void;
  onRejectSelectedIntent: (reason: string) => void;
  onReviseSelectedIntent: (feedback: string) => void;
}

export function CommandCenter({
  intents,
  selectedIntentId,
  isSubmitting,
  systemStatus,
  onSendCommand,
  onSelectIntent,
  onApproveSelectedIntent,
  onRejectSelectedIntent,
  onReviseSelectedIntent,
}: CommandCenterProps) {
  const [inputValue, setInputValue] = useState('');
  const selectedIntent = useMemo(
    () => intents.find((item) => item.id === selectedIntentId) || null,
    [intents, selectedIntentId],
  );

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!inputValue.trim() || isSubmitting) return;
    if (selectedIntent?.status === 'awaiting_review') {
      onReviseSelectedIntent(inputValue.trim());
    } else {
      onSendCommand(inputValue.trim());
    }
    setInputValue('');
  };

  return (
    <div className="flex h-full">
      <aside className="w-[360px] border-r border-border bg-surface-hover">
        <div className="border-b border-border px-5 py-4">
          <div className="text-xs font-semibold uppercase tracking-[0.24em] text-text-secondary">
            Intake Queue
          </div>
          <h3 className="mt-2 text-base font-semibold text-text">自然语言需求审阅</h3>
          <p className="mt-2 text-xs leading-5 text-text-secondary">
            输入自然语言需求后，编排器会先做需求分析与拆解，再进入澄清或待审批状态。
          </p>
        </div>
        <div className="max-h-full overflow-y-auto p-4">
          <div className="space-y-3">
            {intents.length === 0 && (
              <div className="rounded-2xl border border-dashed border-border bg-background px-4 py-5 text-sm text-text-secondary">
                当前仓库还没有 intake 草案。直接在右侧输入需求，或者先执行：
                <div className="mt-3 space-y-1">
                  {(systemStatus?.recommended_actions || []).slice(0, 2).map((command) => (
                    <code key={command} className="block rounded bg-surface px-2 py-1 text-xs text-text">
                      {command}
                    </code>
                  ))}
                </div>
              </div>
            )}
            {intents.map((intent) => {
              const selected = intent.id === selectedIntentId;
              return (
                <button
                  key={intent.id}
                  type="button"
                  onClick={() => onSelectIntent(selected ? null : intent.id)}
                  className={`w-full rounded-2xl border px-4 py-4 text-left transition-all ${
                    selected
                      ? 'border-primary bg-background shadow-sm'
                      : 'border-border bg-background hover:border-primary/40'
                  }`}
                >
                  <div className="flex items-start justify-between gap-3">
                    <div className="min-w-0">
                      <div className="line-clamp-2 text-sm font-semibold text-text">{intent.prompt}</div>
                      <div className="mt-2 text-xs text-text-secondary">{intent.summary || '等待分析结果'}</div>
                    </div>
                    <IntentStatusPill status={intent.status} />
                  </div>
                  {intent.questions.length > 0 && (
                    <div className="mt-3 rounded-xl bg-amber-50 px-3 py-2 text-xs text-amber-900">
                      {intent.questions[0]}
                    </div>
                  )}
                  {intent.promotedEpicIssueNumber && (
                    <div className="mt-3 text-xs font-medium text-emerald-700">
                      已进入任务池 · epic #{intent.promotedEpicIssueNumber}
                    </div>
                  )}
                </button>
              );
            })}
          </div>
        </div>
      </aside>

      <section className="flex min-w-0 flex-1 flex-col bg-background">
        <div className="border-b border-border px-6 py-5">
          <div className="flex items-center justify-between gap-4">
            <div>
              <div className="text-xs font-semibold uppercase tracking-[0.24em] text-text-secondary">
                Orchestrator Prompt
              </div>
              <h3 className="mt-2 text-lg font-semibold text-text">
                {selectedIntent ? '继续澄清或审批当前需求' : '输入自然语言需求'}
              </h3>
            </div>
            {selectedIntent?.status === 'awaiting_review' && (
              <div className="flex items-center gap-2">
                <Button type="button" variant="ghost" onClick={() => void onApproveSelectedIntent()}>
                  <CheckCircle2 className="mr-2 h-4 w-4" />
                  审批入池
                </Button>
                <Button
                  type="button"
                  variant="danger"
                  disabled={isSubmitting || inputValue.trim().length === 0}
                  onClick={() => {
                    onRejectSelectedIntent(inputValue.trim());
                    setInputValue('');
                  }}
                >
                  拒绝
                </Button>
              </div>
            )}
          </div>
        </div>

        <div className="flex-1 overflow-y-auto px-6 py-6">
          {selectedIntent ? (
            <IntentDetail intent={selectedIntent} />
          ) : (
            <div className="rounded-[24px] border border-border bg-surface p-6">
              <div className="flex items-center gap-2 text-text">
                <Layers3 className="h-5 w-5 text-primary" />
                <h4 className="text-base font-semibold">编排器会做什么</h4>
              </div>
              <div className="mt-4 space-y-3 text-sm leading-7 text-text-secondary">
                <p>1. 读取你的自然语言需求，做一次受控 brainstorming。</p>
                <p>2. 若关键信息不足，返回澄清问题，不直接进入任务池。</p>
                <p>3. 若信息足够，生成 epic / story / task proposal，等待审批。</p>
                <p>4. 你审批后，proposal 会 promotion 为 `program_epic` / `program_story` / `work_item`。</p>
                <p>5. 现有 supervisor / worker / agent 链路继续从任务池领取并执行。</p>
              </div>
            </div>
          )}
        </div>

        <div className="border-t border-border bg-surface px-6 py-4">
          <form onSubmit={handleSubmit} className="space-y-3">
            <textarea
              value={inputValue}
              onChange={(e) => setInputValue(e.target.value)}
              placeholder={
                selectedIntent?.status === 'awaiting_clarification'
                  ? `回答澄清问题：${selectedIntent.questions[0] || ''}`
                  : selectedIntent?.status === 'awaiting_review'
                    ? '输入审核意见。提交将作为 revise 反馈；点击“拒绝”会将这里的内容作为拒绝原因。'
                  : '例如：实现一套用户认证能力，先支持 JWT 登录、刷新 token、前端登录页与权限守卫。'
              }
              className="min-h-28 w-full rounded-2xl border border-border bg-background px-4 py-3 text-sm text-text outline-none transition-colors focus:border-primary"
            />
            <div className="flex items-center justify-between gap-3">
              <div className="text-xs text-text-secondary">
                {selectedIntent?.status === 'awaiting_clarification'
                  ? '当前提交会作为补充回答继续分析。'
                  : selectedIntent?.status === 'awaiting_review'
                    ? '当前提交会把审核意见作为 revise 反馈重新进入分析流程。'
                  : '当前提交会创建新的自然语言需求草案。'}
              </div>
              <Button type="submit" disabled={isSubmitting || inputValue.trim().length === 0}>
                <Send className="mr-2 h-4 w-4" />
                {isSubmitting
                  ? '处理中'
                  : selectedIntent?.status === 'awaiting_clarification'
                    ? '提交回答'
                    : selectedIntent?.status === 'awaiting_review'
                      ? '要求修改'
                      : '提交需求'}
              </Button>
            </div>
          </form>
        </div>
      </section>
    </div>
  );
}

function IntentDetail({ intent }: { intent: IntakeIntent }) {
  const stories = intent.proposal.stories || [];
  return (
    <div className="space-y-5">
      <div className="rounded-[24px] border border-border bg-surface p-6">
        <div className="flex items-center gap-2 text-text">
          <HelpCircle className="h-5 w-5 text-primary" />
          <h4 className="text-base font-semibold">当前分析结果</h4>
        </div>
        <p className="mt-4 text-sm leading-7 text-text-secondary">{intent.summary || '尚未返回摘要。'}</p>
        {intent.reviewFeedback && (
          <div className="mt-5 rounded-2xl border border-border bg-background px-4 py-4">
            <div className="text-xs font-semibold uppercase tracking-wide text-text-secondary">最近审核</div>
            <div className="mt-2 text-sm font-medium text-text">
              {intent.reviewAction === 'reject' ? 'Reject' : intent.reviewAction === 'revise' ? 'Revise' : 'Approve'}
              {intent.reviewedBy ? ` · ${intent.reviewedBy}` : ''}
            </div>
            <div className="mt-2 text-sm leading-6 text-text-secondary">{intent.reviewFeedback}</div>
          </div>
        )}
        {intent.questions.length > 0 && (
          <div className="mt-5 rounded-2xl border border-amber-200 bg-amber-50 px-4 py-4">
            <div className="text-sm font-semibold text-amber-900">待补充信息</div>
            <ul className="mt-3 list-disc space-y-2 pl-5 text-sm text-amber-900">
              {intent.questions.map((question) => (
                <li key={question}>{question}</li>
              ))}
            </ul>
          </div>
        )}
      </div>

      <div className="rounded-[24px] border border-border bg-surface p-6">
        <h4 className="text-base font-semibold text-text">Proposal</h4>
        <div className="mt-4 space-y-4">
          <div className="rounded-2xl border border-border bg-background px-4 py-4">
            <div className="text-xs font-semibold uppercase tracking-wide text-text-secondary">Epic</div>
            <div className="mt-2 text-sm font-semibold text-text">
              {String(intent.proposal.epic?.title || '未生成 epic 标题')}
            </div>
          </div>
          <div className="grid gap-4 xl:grid-cols-2">
            {stories.map((story, index) => (
              <div key={`${story.story_key || index}-${story.title}`} className="rounded-2xl border border-border bg-background px-4 py-4">
                <div className="text-xs font-semibold uppercase tracking-wide text-text-secondary">
                  Story {story.story_key || index + 1}
                </div>
                <div className="mt-2 text-sm font-semibold text-text">{story.title}</div>
                <div className="mt-2 text-xs text-text-secondary">
                  lane: {story.lane || '—'} · complexity: {story.complexity || '—'}
                </div>
                {(story.tasks || []).length > 0 && (
                  <div className="mt-4 space-y-2">
                    {(story.tasks || []).map((task, taskIndex) => (
                      <div key={`${task.task_key || taskIndex}-${task.title}`} className="rounded-xl bg-surface px-3 py-3">
                        <div className="text-sm font-medium text-text">{task.title}</div>
                        <div className="mt-1 text-xs text-text-secondary">
                          wave: {task.wave || '—'} · type: {task.task_type || 'core_path'}
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}

function IntentStatusPill({ status }: { status: IntakeIntent['status'] }) {
  const mapping: Record<IntakeIntent['status'], string> = {
    awaiting_clarification: 'bg-amber-50 text-amber-900',
    awaiting_review: 'bg-blue-50 text-blue-900',
    promoted: 'bg-emerald-50 text-emerald-900',
    rejected: 'bg-rose-50 text-rose-900',
  };
  const label: Record<IntakeIntent['status'], string> = {
    awaiting_clarification: '待澄清',
    awaiting_review: '待审批',
    promoted: '已入池',
    rejected: '已拒绝',
  };
  return (
    <span className={`shrink-0 rounded-full px-2 py-1 text-[11px] font-semibold ${mapping[status]}`}>
      {label[status]}
    </span>
  );
}
