import { describe, expect, it, vi } from 'vitest';

import type { CommandMessage } from '../types';
import type { IntakeMutationResponse } from '../api';
import {
  buildIntentSystemMessage,
  createInitialIntakeState,
  createIntakeSlice,
  mapIntentToDisplay,
} from '../stores/console-intake-slice';

function createHarness(
  overrides: Partial<{
    repo: string;
    commandHistory: CommandMessage[];
    selectedIntentId: string | null;
  }> = {},
  depsOverrides: Partial<Parameters<typeof createIntakeSlice>[0]> = {},
) {
  const loadRepo = vi.fn(async () => undefined);
  const deps = {
    submitIntent: vi.fn(async () => ({ intent_id: 'intent-1', repo: 'demo/repo', status: 'awaiting_review' })),
    answerIntent: vi.fn(async () => ({ intent_id: 'intent-1', repo: 'demo/repo', status: 'awaiting_review' })),
    approveIntent: vi.fn(async () => ({ intent_id: 'intent-1', repo: 'demo/repo', status: 'promoted', promoted_epic_issue_number: 88 })),
    rejectIntent: vi.fn(async () => ({ intent_id: 'intent-1', repo: 'demo/repo', status: 'rejected', summary: '已拒绝该提案。' })),
    reviseIntent: vi.fn(async () => ({
      intent_id: 'intent-1',
      repo: 'demo/repo',
      status: 'awaiting_review',
      summary: '已重新拆解。',
    })),
    ...depsOverrides,
  };

  let state = {
    repo: 'demo/repo',
    error: null as string | null,
    actionNotice: null as string | null,
    loadRepo,
    ...createInitialIntakeState(),
  };

  const setState = (
    partial:
      | Partial<typeof state>
      | ((current: typeof state) => Partial<typeof state>),
  ) => {
    const patch = typeof partial === 'function' ? partial(state) : partial;
    state = { ...state, ...patch };
  };
  const getState = () => state;

  const slice = createIntakeSlice(deps)(setState as never, getState as never, {} as never);
  state = { ...state, ...slice, ...overrides };

  return {
    deps,
    getState,
    loadRepo,
  };
}

describe('console intake slice', () => {
  it('maps review metadata when converting API intents to display intents', () => {
    expect(
      mapIntentToDisplay({
        id: 'intent-1',
        repo: 'demo/repo',
        prompt: '实现认证系统',
        status: 'awaiting_review',
        summary: '拆解完成',
        clarification_questions_json: ['是否只支持 Web？'],
        proposal_json: {
          epic: { title: 'Auth' },
          stories: [{ title: 'Backend auth' }],
        },
        promoted_epic_issue_number: 42,
        approved_by: 'alice',
        reviewed_at: '2026-04-06T08:00:00Z',
        reviewed_by: 'bob',
        review_action: 'revise',
        review_feedback: '请缩小范围',
      }),
    ).toMatchObject({
      id: 'intent-1',
      questions: ['是否只支持 Web？'],
      promotedEpicIssueNumber: 42,
      approvedBy: 'alice',
      reviewedBy: 'bob',
      reviewAction: 'revise',
      reviewFeedback: '请缩小范围',
    });
  });

  it('builds clarification and promoted system messages', () => {
    expect(
      buildIntentSystemMessage(
        {
          intent_id: 'intent-1',
          repo: 'demo/repo',
          status: 'awaiting_clarification',
          summary: '还缺少执行边界。',
          questions: ['是否允许改数据库结构？', '验收命令是什么？'],
        } as IntakeMutationResponse,
        false,
      ),
    ).toContain('需要补充：\n- 是否允许改数据库结构？\n- 验收命令是什么？');

    expect(
      buildIntentSystemMessage(
        {
          intent_id: 'intent-1',
          repo: 'demo/repo',
          status: 'promoted',
          promoted_epic_issue_number: 77,
        } as IntakeMutationResponse,
        true,
      ),
    ).toBe('已提升到任务池，epic #77。');
  });

  it('validates blank reject reason before calling the API', async () => {
    const { deps, getState } = createHarness({ selectedIntentId: 'intent-1' });

    await getState().rejectSelectedIntent('   ');

    expect(getState().error).toBe('请输入拒绝原因。');
    expect(deps.rejectIntent).not.toHaveBeenCalled();
  });

  it('submits revise feedback, keeps the selected intent, and reloads repo data', async () => {
    const { deps, getState, loadRepo } = createHarness({
      selectedIntentId: 'intent-1',
      commandHistory: [],
    });

    await getState().reviseSelectedIntent('请把范围缩到登录和刷新 token');

    expect(deps.reviseIntent).toHaveBeenCalledWith(
      'intent-1',
      'console-operator',
      '请把范围缩到登录和刷新 token',
    );
    expect(getState().selectedIntentId).toBe('intent-1');
    expect(getState().actionNotice).toBe('审核意见已提交，需求已重新进入分析流程');
    expect(getState().commandHistory.at(-1)?.type).toBe('system');
    expect(loadRepo).toHaveBeenCalledWith('demo/repo');
  });
});
