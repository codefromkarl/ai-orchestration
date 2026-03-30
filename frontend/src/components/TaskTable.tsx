import { WorkItem } from '../types';
import { Badge } from './Badge';
import { getPriorityLabel } from '../utils/status-utils';

interface TaskTableProps {
  items: WorkItem[];
  onRowClick: (item: WorkItem) => void;
  totalCount?: number;
}

export function TaskTable({ items, onRowClick, totalCount }: TaskTableProps) {
  const effectiveTotal = typeof totalCount === 'number' ? totalCount : items.length;
  const showRepoColumn = items.some((item) => Boolean(item.repo));
  return (
    <div className="flex flex-col h-full">
      <div className="p-4 border-b border-border bg-surface">
        <div className="text-sm text-text-secondary">
          显示 {items.length} / {effectiveTotal} 个任务
        </div>
      </div>

      <div className="flex-1 overflow-auto">
        <table className="w-full">
          <thead className="border-b sticky top-0 bg-surface-hover border-border">
            <tr>
              <th 
                className="px-4 py-3 text-left text-xs font-semibold uppercase tracking-wider text-text-secondary"
              >
                编号
              </th>
              {showRepoColumn && (
                <th className="px-4 py-3 text-left text-xs font-semibold uppercase tracking-wider text-text-secondary">
                  仓库
                </th>
              )}
              <th 
                className="px-4 py-3 text-left text-xs font-semibold uppercase tracking-wider text-text-secondary"
              >
                标题
              </th>
              <th 
                className="px-4 py-3 text-left text-xs font-semibold uppercase tracking-wider text-text-secondary"
              >
                Epic
              </th>
              <th 
                className="px-4 py-3 text-left text-xs font-semibold uppercase tracking-wider text-text-secondary"
              >
                Story
              </th>
              <th 
                className="px-4 py-3 text-left text-xs font-semibold uppercase tracking-wider text-text-secondary"
              >
                状态
              </th>
              <th 
                className="px-4 py-3 text-left text-xs font-semibold uppercase tracking-wider text-text-secondary"
              >
                优先级
              </th>
              <th 
                className="px-4 py-3 text-left text-xs font-semibold uppercase tracking-wider text-text-secondary"
              >
                阻塞
              </th>
            </tr>
          </thead>
          <tbody className="divide-y bg-surface border-border">
            {items.map((item) => (
              <tr
                key={item.repo ? `${item.repo}-${item.number}` : item.number}
                onClick={() => onRowClick(item)}
                className="cursor-pointer transition-colors bg-surface hover:bg-surface-hover"
              >
                <td className="px-4 py-3 text-sm font-medium text-text">
                  #{item.number}
                </td>
                {showRepoColumn && (
                  <td className="px-4 py-3 text-sm text-text-secondary">
                    {item.repo || '—'}
                  </td>
                )}
                <td className="px-4 py-3 text-sm text-text">
                  <div className="max-w-md truncate">{item.title}</div>
                </td>
                <td className="px-4 py-3 text-sm text-text-secondary">
                  {item.epicNumber ? `#${item.epicNumber}` : '—'}
                </td>
                <td className="px-4 py-3 text-sm text-text-secondary">
                  {item.storyNumber ? `#${item.storyNumber}` : '—'}
                </td>
                <td className="px-4 py-3">
                  <Badge status={item.status} />
                </td>
                <td className="px-4 py-3 text-sm text-text">
                  {getPriorityLabel(item.priority)}
                </td>
                <td className="px-4 py-3 text-sm text-red-600">
                  {item.blockedReason || '—'}
                </td>
              </tr>
            ))}
            {items.length === 0 && (
              <tr>
                <td
                  colSpan={showRepoColumn ? 8 : 7}
                  className="px-4 py-8 text-center text-sm text-text-secondary"
                >
                  没有符合当前筛选条件的任务。
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
