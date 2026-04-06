import { Cpu, FolderTree, Settings, TerminalSquare, Wrench, X } from 'lucide-react';
import { SystemStatus } from '../types';

interface SystemPanelProps {
  mode: 'model' | 'system' | null;
  systemStatus: SystemStatus | null;
  onClose: () => void;
}

export function SystemPanel({ mode, systemStatus, onClose }: SystemPanelProps) {
  if (!mode) return null;

  const title = mode === 'system' ? '系统配置' : '模型配置';

  return (
    <div className="absolute inset-0 z-30 flex items-start justify-end bg-black/20">
      <aside className="h-full w-full max-w-xl border-l border-border bg-background shadow-2xl">
        <div className="flex items-start justify-between border-b border-border px-6 py-5">
          <div>
            <div className="text-xs font-semibold uppercase tracking-[0.24em] text-text-secondary">
              Control Surface
            </div>
            <h2 className="mt-1 text-xl font-semibold text-text">{title}</h2>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="rounded-md p-2 text-text-secondary transition-colors hover:bg-surface-hover hover:text-text"
            aria-label="关闭配置面板"
          >
            <X className="h-5 w-5" />
          </button>
        </div>

        {mode === 'model' ? (
          <div className="space-y-4 p-6">
            <div className="rounded-2xl border border-border bg-surface p-5">
              <div className="flex items-center gap-3 text-text">
                <Cpu className="h-5 w-5 text-primary" />
                <span className="text-sm font-medium">模型路由尚未开放到控制台</span>
              </div>
              <p className="mt-3 text-sm leading-6 text-text-secondary">
                当前仓库已经具备执行器路由和 provider 基础设施，但 UI 侧还没有把模型配置编辑能力接出来。
                下一步更适合直接接 executor routing profile 和 provider 配置读取接口，而不是继续做前端占位。
              </p>
            </div>
          </div>
        ) : (
          <div className="space-y-5 overflow-y-auto p-6">
            <section className="rounded-2xl border border-border bg-surface p-5">
              <div className="flex items-center gap-3">
                <Settings className="h-5 w-5 text-primary" />
                <div>
                  <h3 className="text-sm font-semibold text-text">系统状态</h3>
                  <p className="text-xs text-text-secondary">当前控制台所感知到的本地配置与依赖。</p>
                </div>
              </div>
              <div className="mt-4 grid gap-3 sm:grid-cols-2">
                <StatusTile label="配置文件" value={systemStatus?.config_source || '未发现 taskplane.toml'} tone={systemStatus?.config_source ? 'ok' : 'warn'} />
                <StatusTile label="数据库连接" value={systemStatus?.database_connected ? '已连接' : (systemStatus?.database_error || '未连接')} tone={systemStatus?.database_connected ? 'ok' : 'warn'} />
                <StatusTile label="Compose 文件" value={systemStatus?.dev_compose_file || 'ops/docker-compose.nocodb.yml'} tone="neutral" />
                <StatusTile label="Env 文件" value={systemStatus?.dev_env_file || '.env'} tone="neutral" />
              </div>
            </section>

            <section className="rounded-2xl border border-border bg-surface p-5">
              <div className="flex items-center gap-3">
                <Wrench className="h-5 w-5 text-primary" />
                <div>
                  <h3 className="text-sm font-semibold text-text">依赖命令</h3>
                  <p className="text-xs text-text-secondary">用于本地启动、导入和前端构建的关键二进制。</p>
                </div>
              </div>
              <div className="mt-4 grid gap-2">
                {Object.entries(systemStatus?.commands || {}).map(([name, info]) => (
                  <div key={name} className="flex items-center justify-between rounded-xl border border-border bg-background px-3 py-2">
                    <span className="text-sm font-medium text-text">{name}</span>
                    <span className={`text-xs ${info.available ? 'text-emerald-600' : 'text-amber-600'}`}>
                      {info.available ? (info.path || 'available') : 'missing'}
                    </span>
                  </div>
                ))}
              </div>
            </section>

            <section className="rounded-2xl border border-border bg-surface p-5">
              <div className="flex items-center gap-3">
                <FolderTree className="h-5 w-5 text-primary" />
                <div>
                  <h3 className="text-sm font-semibold text-text">Console Repo 映射</h3>
                  <p className="text-xs text-text-secondary">用于分解任务和查看日志的本地工作目录配置。</p>
                </div>
              </div>
              <div className="mt-4 space-y-3">
                {(systemStatus?.configured_repos || []).length === 0 && (
                  <div className="rounded-xl border border-dashed border-border bg-background px-4 py-4 text-sm text-text-secondary">
                    还没有配置 repo workdir / logdir。复制 `taskplane.toml.example` 后填入你的项目目录。
                  </div>
                )}
                {(systemStatus?.configured_repos || []).map((repo) => (
                  <div key={repo.repo} className="rounded-xl border border-border bg-background px-4 py-3">
                    <div className="text-sm font-semibold text-text">{repo.repo}</div>
                    <div className="mt-2 text-xs text-text-secondary">workdir: {repo.workdir || '未配置'}</div>
                    <div className="mt-1 text-xs text-text-secondary">log dir: {repo.log_dir || '未配置'}</div>
                    <div className="mt-2 flex gap-2 text-[11px]">
                      <span className={`rounded-full px-2 py-1 ${repo.workdir_exists ? 'bg-emerald-50 text-emerald-700' : 'bg-amber-50 text-amber-700'}`}>
                        workdir {repo.workdir_exists ? 'ok' : 'missing'}
                      </span>
                      <span className={`rounded-full px-2 py-1 ${repo.log_dir_exists ? 'bg-emerald-50 text-emerald-700' : 'bg-amber-50 text-amber-700'}`}>
                        log dir {repo.log_dir_exists ? 'ok' : 'missing'}
                      </span>
                    </div>
                  </div>
                ))}
              </div>
            </section>

            <section className="rounded-2xl border border-border bg-surface p-5">
              <div className="flex items-center gap-3">
                <TerminalSquare className="h-5 w-5 text-primary" />
                <div>
                  <h3 className="text-sm font-semibold text-text">推荐命令</h3>
                  <p className="text-xs text-text-secondary">按这个顺序执行，最快能把控制台带到可观察状态。</p>
                </div>
              </div>
              <div className="mt-4 space-y-2">
                {(systemStatus?.recommended_actions || []).map((command) => (
                  <pre key={command} className="overflow-x-auto rounded-xl border border-border bg-background px-3 py-2 text-xs text-text">
                    <code>{command}</code>
                  </pre>
                ))}
              </div>
            </section>
          </div>
        )}
      </aside>
    </div>
  );
}

function StatusTile({ label, value, tone }: { label: string; value: string; tone: 'ok' | 'warn' | 'neutral' }) {
  const toneClass = tone === 'ok'
    ? 'text-emerald-700'
    : tone === 'warn'
      ? 'text-amber-700'
      : 'text-text';
  return (
    <div className="rounded-xl border border-border bg-background px-4 py-3">
      <div className="text-[11px] uppercase tracking-wide text-text-secondary">{label}</div>
      <div className={`mt-2 text-sm font-medium ${toneClass}`}>{value}</div>
    </div>
  );
}
