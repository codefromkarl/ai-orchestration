import { TaskStatus } from '../types';
import { getStatusLabel } from '../utils/status-utils';

interface BadgeProps {
  status: TaskStatus;
}

export function Badge({ status }: BadgeProps) {
  const label = getStatusLabel(status);

  return (
    <span className={`badge badge-${status}`}>
      {label}
    </span>
  );
}
