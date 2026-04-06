import type { StateCreator } from 'zustand';

import type {
  IntakeMutationResponse,
  IntentsResponse,
} from '../api';
import type {
  CommandMessage,
  IntakeIntent,
} from '../types';

export interface IntakeSliceState {
  intents: IntakeIntent[];
  commandHistory: CommandMessage[];
  selectedIntentId: string | null;
  isIntakeSubmitting: boolean;
}

export interface IntakeSliceActions {
  handleSendCommand: (command: string) => void;
  selectIntent: (intentId: string | null) => void;
  approveSelectedIntent: () => Promise<void>;
  rejectSelectedIntent: (reason: string) => Promise<void>;
  reviseSelectedIntent: (feedback: string) => Promise<void>;
}

export interface IntakeSliceHost {
  repo: string;
  error: string | null;
  actionNotice: string | null;
  loadRepo: (repoName: string) => Promise<void>;
}

export type IntakeSliceStore = IntakeSliceState & IntakeSliceActions & IntakeSliceHost;

export interface IntakeSliceDependencies {
  submitIntent: (repo: string, prompt: string) => Promise<IntakeMutationResponse>;
  answerIntent: (intentId: string, answer: string) => Promise<IntakeMutationResponse>;
  approveIntent: (intentId: string, approver: string) => Promise<IntakeMutationResponse>;
  rejectIntent: (
    intentId: string,
    reviewer: string,
    reason: string,
  ) => Promise<IntakeMutationResponse>;
  reviseIntent: (
    intentId: string,
    reviewer: string,
    feedback: string,
  ) => Promise<IntakeMutationResponse>;
}

export function createInitialIntakeState(): IntakeSliceState {
  return {
    intents: [],
    commandHistory: [],
    selectedIntentId: null,
    isIntakeSubmitting: false,
  };
}

export function mapIntentToDisplay(
  item: IntentsResponse['items'][number],
): IntakeIntent {
  return {
    id: item.id,
    repo: item.repo,
    prompt: item.prompt,
    status: item.status as IntakeIntent['status'],
    summary: item.summary || '',
    questions: item.clarification_questions_json || [],
    proposal: item.proposal_json || {},
    promotedEpicIssueNumber: item.promoted_epic_issue_number,
    approvedBy: item.approved_by,
    reviewedAt: item.reviewed_at,
    reviewedBy: item.reviewed_by,
    reviewAction: item.review_action as IntakeIntent['reviewAction'],
    reviewFeedback: item.review_feedback,
  };
}

export function buildIntentSystemMessage(
  response: IntakeMutationResponse,
  isAnswer: boolean,
): string {
  const summary = response.summary?.trim() || '已更新。';
  if (response.status === 'awaiting_clarification') {
    const questions = (response.questions || []).map((item) => `- ${item}`).join('\n');
    return `${isAnswer ? '已收到补充。' : '已创建需求草案。'}\n${summary}${questions ? `\n\n需要补充：\n${questions}` : ''}`;
  }
  if (response.status === 'awaiting_review') {
    return `${summary}\n\n拆解已经完成，等待你审批进入任务池。`;
  }
  if (response.status === 'promoted') {
    return `已提升到任务池，epic #${response.promoted_epic_issue_number ?? '—'}。`;
  }
  return summary;
}

function createSystemMessage(content: string): CommandMessage {
  return {
    id: `msg-${Date.now()}-system`,
    type: 'system',
    content,
    timestamp: new Date(),
  };
}

function createUserMessage(content: string): CommandMessage {
  return {
    id: `msg-${Date.now()}-user`,
    type: 'user',
    content,
    timestamp: new Date(),
  };
}

export function createIntakeSlice(
  deps: IntakeSliceDependencies,
): StateCreator<IntakeSliceStore, [], [], IntakeSliceState & IntakeSliceActions> {
  return (set, get) => ({
    ...createInitialIntakeState(),

    handleSendCommand: (command: string) => {
      const { commandHistory, repo, selectedIntentId } = get();
      if (!repo) {
        set({ error: '请先选择仓库后再提交需求。' });
        return;
      }

      set({
        commandHistory: [...commandHistory, createUserMessage(command)],
        isIntakeSubmitting: true,
        error: null,
      });

      void (async () => {
        try {
          const response = selectedIntentId
            ? await deps.answerIntent(selectedIntentId, command)
            : await deps.submitIntent(repo, command);

          set((current) => ({
            commandHistory: [
              ...current.commandHistory,
              createSystemMessage(buildIntentSystemMessage(response, selectedIntentId !== null)),
            ],
            selectedIntentId: response.status === 'awaiting_clarification'
              ? response.intent_id
              : null,
            actionNotice: response.status === 'promoted'
              ? `需求已进入任务池：epic #${response.promoted_epic_issue_number ?? '—'}`
              : null,
            isIntakeSubmitting: false,
          }));
          await get().loadRepo(repo);
        } catch (error) {
          const message = error instanceof Error ? error.message : '需求提交失败';
          set((current) => ({
            commandHistory: [
              ...current.commandHistory,
              createSystemMessage(`提交失败：${message}`),
            ],
            error: message,
            isIntakeSubmitting: false,
          }));
        }
      })();
    },

    selectIntent: (intentId) => set({ selectedIntentId: intentId }),

    approveSelectedIntent: async () => {
      const { selectedIntentId, repo } = get();
      if (!selectedIntentId || !repo) {
        return;
      }

      set({ isIntakeSubmitting: true, error: null });
      try {
        const response = await deps.approveIntent(selectedIntentId, 'console-operator');
        set((current) => ({
          commandHistory: [
            ...current.commandHistory,
            createSystemMessage(`审批通过，已提升到任务池。epic #${response.promoted_epic_issue_number ?? '—'}`),
          ],
          selectedIntentId: null,
          isIntakeSubmitting: false,
          actionNotice: `审批已通过：epic #${response.promoted_epic_issue_number ?? '—'} 已进入任务池`,
        }));
        await get().loadRepo(repo);
      } catch (error) {
        set({
          error: error instanceof Error ? error.message : '审批失败',
          isIntakeSubmitting: false,
        });
      }
    },

    rejectSelectedIntent: async (reason: string) => {
      const { selectedIntentId, repo } = get();
      if (!selectedIntentId || !repo) {
        return;
      }

      const reasonText = reason.trim();
      if (!reasonText) {
        set({ error: '请输入拒绝原因。' });
        return;
      }

      set({ isIntakeSubmitting: true, error: null });
      try {
        const response = await deps.rejectIntent(
          selectedIntentId,
          'console-operator',
          reasonText,
        );
        set((current) => ({
          commandHistory: [
            ...current.commandHistory,
            createSystemMessage(response.summary?.trim() || `已拒绝当前 proposal：${reasonText}`),
          ],
          selectedIntentId: null,
          isIntakeSubmitting: false,
          actionNotice: '当前 intake proposal 已拒绝',
        }));
        await get().loadRepo(repo);
      } catch (error) {
        set({
          error: error instanceof Error ? error.message : '拒绝失败',
          isIntakeSubmitting: false,
        });
      }
    },

    reviseSelectedIntent: async (feedback: string) => {
      const { selectedIntentId, repo } = get();
      if (!selectedIntentId || !repo) {
        return;
      }

      const feedbackText = feedback.trim();
      if (!feedbackText) {
        set({ error: '请输入修改意见。' });
        return;
      }

      set({ isIntakeSubmitting: true, error: null });
      try {
        const response = await deps.reviseIntent(
          selectedIntentId,
          'console-operator',
          feedbackText,
        );
        set((current) => ({
          commandHistory: [
            ...current.commandHistory,
            createSystemMessage(buildIntentSystemMessage(response, true)),
          ],
          selectedIntentId: response.status === 'awaiting_review'
            || response.status === 'awaiting_clarification'
            ? response.intent_id
            : null,
          isIntakeSubmitting: false,
          actionNotice: '审核意见已提交，需求已重新进入分析流程',
        }));
        await get().loadRepo(repo);
      } catch (error) {
        set({
          error: error instanceof Error ? error.message : '提交修改意见失败',
          isIntakeSubmitting: false,
        });
      }
    },
  });
}
