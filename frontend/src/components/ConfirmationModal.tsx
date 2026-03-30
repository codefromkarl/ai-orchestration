import { useConsoleStore } from '../stores/console-store';

export function ConfirmationModal() {
  const pendingAction = useConsoleStore((s) => s.pendingAction);
  const actionError = useConsoleStore((s) => s.actionError);
  const isActionSubmitting = useConsoleStore((s) => s.isActionSubmitting);
  const handleConfirmAction = useConsoleStore((s) => s.handleConfirmAction);
  const handleCancelAction = useConsoleStore((s) => s.handleCancelAction);
  const locale = useConsoleStore((s) => s.locale);

  if (!pendingAction) return null;

  return (
    <div
      id="confirmation-modal"
      aria-hidden="false"
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 px-4"
    >
      <div className="w-full max-w-md rounded-xl border border-border bg-surface p-5">
        <div className="mb-2 text-lg font-semibold text-text">
          {locale === 'zh' ? '确认操作' : 'Confirm action'}
        </div>
        <div className="mb-4 text-sm text-text-secondary">
          {`${pendingAction.label} · ${pendingAction.actionUrl}`}
        </div>
        {actionError && (
          <div className="mb-4 rounded-md border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">
            {actionError}
          </div>
        )}
        <div className="flex justify-end gap-2">
          <button
            id="cancel-modal-btn"
            type="button"
            disabled={isActionSubmitting}
            onClick={handleCancelAction}
            className="rounded-md border border-border bg-surface-hover px-3 py-2 text-sm text-text hover:bg-surface"
          >
            {locale === 'zh' ? '取消' : 'Cancel'}
          </button>
          <button
            id="confirm-modal-btn"
            type="button"
            disabled={isActionSubmitting || !pendingAction}
            onClick={() => void handleConfirmAction()}
            className="rounded-md px-3 py-2 text-sm font-medium text-white disabled:cursor-not-allowed disabled:opacity-60 bg-primary"
          >
            {isActionSubmitting
              ? (locale === 'zh' ? '提交中…' : 'Submitting…')
              : (locale === 'zh' ? '确认' : 'Confirm')}
          </button>
        </div>
      </div>
    </div>
  );
}
