import { ArrowRight, DatabaseZap, PlayCircle, Settings2 } from 'lucide-react';
import { SystemStatus } from '../types';

interface ConsoleOnboardingProps {
  repo: string;
  systemStatus: SystemStatus | null;
  onOpenSystemPanel: () => void;
}

export function ConsoleOnboarding({ repo, systemStatus, onOpenSystemPanel }: ConsoleOnboardingProps) {
  const recommendations = systemStatus?.recommended_actions || [
    'cp taskplane.toml.example taskplane.toml',
    'taskplane-dev up',
    'taskplane-demo seed --repo demo/taskplane --reset',
    'taskplane-doctor --repo demo/taskplane',
  ];

  return (
    <section className="h-full overflow-auto bg-background px-6 py-8">
      <div className="mx-auto max-w-5xl space-y-6">
        <div className="relative overflow-hidden rounded-[28px] border border-border bg-[linear-gradient(135deg,#f8fafc_0%,#eef2ff_42%,#fef3c7_100%)] p-8 shadow-md">
          <div className="absolute -right-10 -top-10 h-40 w-40 rounded-full bg-white/50 blur-2xl" />
          <div className="relative max-w-2xl">
            <div className="text-xs font-semibold uppercase tracking-[0.3em] text-slate-600">First Run</div>
            <h2 className="mt-3 text-3xl font-semibold tracking-tight text-slate-900">
              控制台已经就绪，但当前还没有可展示的数据面。
            </h2>
            <p className="mt-4 text-sm leading-7 text-slate-700">
              {repo
                ? `当前仓库上下文是 ${repo}。如果它还没出现在控制台里，通常意味着本地配置、数据库或 demo 数据还没准备好。`
                : '当前还没有选中的仓库。通常先补配置，再启动本地依赖，然后注入 demo 数据或导入真实仓库。'}
            </p>
            <div className="mt-6 flex flex-wrap gap-3">
              <button
                type="button"
                onClick={onOpenSystemPanel}
                className="inline-flex items-center gap-2 rounded-full bg-slate-900 px-4 py-2 text-sm font-medium text-white transition-transform hover:-translate-y-0.5"
              >
                <Settings2 className="h-4 w-4" />
                打开系统面板
              </button>
              <span className="inline-flex items-center gap-2 rounded-full border border-slate-300 bg-white/80 px-4 py-2 text-sm text-slate-700">
                <DatabaseZap className="h-4 w-4" />
                {systemStatus?.database_connected ? '数据库已连通' : '数据库尚未连通'}
              </span>
            </div>
          </div>
        </div>

        <div className="grid gap-4 lg:grid-cols-[1.4fr_1fr]">
          <div className="rounded-[24px] border border-border bg-surface p-6">
            <div className="flex items-center gap-2 text-text">
              <PlayCircle className="h-5 w-5 text-primary" />
              <h3 className="text-base font-semibold">推荐启动顺序</h3>
            </div>
            <div className="mt-5 space-y-3">
              {recommendations.map((command, index) => (
                <div key={command} className="flex items-start gap-3 rounded-2xl border border-border bg-background px-4 py-3">
                  <div className="mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-primary text-xs font-semibold text-white">
                    {index + 1}
                  </div>
                  <div className="min-w-0">
                    <code className="block overflow-x-auto whitespace-pre-wrap text-sm text-text">{command}</code>
                  </div>
                </div>
              ))}
            </div>
          </div>

          <div className="rounded-[24px] border border-border bg-surface p-6">
            <h3 className="text-base font-semibold text-text">当前判定</h3>
            <div className="mt-4 space-y-3 text-sm text-text-secondary">
              <div className="rounded-2xl border border-border bg-background px-4 py-3">
                配置文件
                <div className="mt-1 font-medium text-text">
                  {systemStatus?.config_source || '未发现 taskplane.toml'}
                </div>
              </div>
              <div className="rounded-2xl border border-border bg-background px-4 py-3">
                已发现仓库
                <div className="mt-1 font-medium text-text">
                  {systemStatus?.discovered_repositories.length ? systemStatus.discovered_repositories.join(', ') : '暂无'}
                </div>
              </div>
              <div className="rounded-2xl border border-border bg-background px-4 py-3">
                Console 映射
                <div className="mt-1 font-medium text-text">
                  {(systemStatus?.configured_repos.length || 0) > 0
                    ? `${systemStatus?.configured_repos.length} 个 repo 已配置`
                    : '尚未配置 repo workdir / logdir'}
                </div>
              </div>
            </div>
            <button
              type="button"
              onClick={onOpenSystemPanel}
              className="mt-5 inline-flex items-center gap-2 text-sm font-medium text-primary hover:text-primary-hover"
            >
              查看详细诊断
              <ArrowRight className="h-4 w-4" />
            </button>
          </div>
        </div>
      </div>
    </section>
  );
}
