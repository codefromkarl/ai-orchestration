interface SkeletonLoaderProps {
  variant?: 'kanban' | 'table' | 'hierarchy';
  count?: number;
}

function KanbanSkeleton() {
  return (
    <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3 p-6">
      {Array.from({ length: 6 }, (_, i) => (
        <div
          key={i}
          className="rounded-xl border border-border bg-surface p-4 animate-pulse"
        >
          <div className="h-3 w-16 rounded bg-surface-hover" />
          <div className="mt-3 h-5 w-3/4 rounded bg-surface-hover" />
          <div className="mt-2 h-4 w-1/2 rounded bg-surface-hover" />
          <div className="mt-4 flex gap-2">
            <div className="h-5 w-12 rounded-full bg-surface-hover" />
            <div className="h-5 w-12 rounded-full bg-surface-hover" />
            <div className="h-5 w-12 rounded-full bg-surface-hover" />
          </div>
        </div>
      ))}
    </div>
  );
}

function TableSkeleton() {
  return (
    <div className="p-4">
      <div className="h-4 w-48 rounded bg-surface-hover animate-pulse" />
      <div className="mt-4 space-y-3">
        {Array.from({ length: 8 }, (_, i) => (
          <div key={i} className="flex gap-4 py-3 animate-pulse">
            <div className="h-4 w-12 rounded bg-surface-hover" />
            <div className="h-4 flex-1 rounded bg-surface-hover" />
            <div className="h-4 w-20 rounded bg-surface-hover" />
            <div className="h-4 w-16 rounded-full bg-surface-hover" />
          </div>
        ))}
      </div>
    </div>
  );
}

function HierarchySkeleton() {
  return (
    <div className="flex gap-4 p-6">
      <div className="flex-1 animate-pulse">
        <div className="h-64 rounded-xl border border-border bg-surface" />
      </div>
      <div className="w-96 shrink-0 animate-pulse">
        <div className="h-8 w-3/4 rounded bg-surface-hover" />
        <div className="mt-2 h-6 w-1/2 rounded bg-surface-hover" />
        <div className="mt-4 space-y-2">
          <div className="h-4 w-full rounded bg-surface-hover" />
          <div className="h-4 w-3/4 rounded bg-surface-hover" />
          <div className="h-4 w-full rounded bg-surface-hover" />
        </div>
      </div>
    </div>
  );
}

export function SkeletonLoader({ variant = 'kanban', count = 1 }: SkeletonLoaderProps) {
  // count is used to control how many skeleton blocks to show for kanban
  void count;

  switch (variant) {
    case 'table':
      return <TableSkeleton />;
    case 'hierarchy':
      return <HierarchySkeleton />;
    default:
      return <KanbanSkeleton />;
  }
}
