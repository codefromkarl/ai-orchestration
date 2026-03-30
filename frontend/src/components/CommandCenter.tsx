import { useState } from 'react';
import { Send } from 'lucide-react';
import { AttentionItem, CommandMessage } from '../types';
import { Button } from './Button';

interface CommandCenterProps {
  attentionItems: AttentionItem[];
  commandHistory: CommandMessage[];
  onSendCommand: (command: string) => void;
}

export function CommandCenter({ attentionItems, commandHistory, onSendCommand }: CommandCenterProps) {
  const [inputValue, setInputValue] = useState('');

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (inputValue.trim()) {
      onSendCommand(inputValue.trim());
      setInputValue('');
    }
  };

  return (
    <div className="flex h-full">
      <div className="w-80 border-r p-4 border-border bg-surface-hover">
        <h3 className="font-semibold mb-4 text-text">
          待处理事项
        </h3>
        <div className="space-y-2">
          {attentionItems.map((item) => (
            <div
              key={item.id}
              className="p-3 border rounded-lg hover:shadow-sm transition-shadow cursor-pointer bg-surface border-border"
            >
              <div className="flex items-start justify-between mb-1">
                <span className="text-sm font-medium text-text">
                  #{item.issueNumber}
                </span>
                <span className="text-xs font-semibold text-orange-600 bg-orange-50 px-2 py-0.5 rounded-full">
                  {item.priorityScore}
                </span>
              </div>
              <p className="text-sm mb-2 line-clamp-2 text-text">
                {item.title}
              </p>
              <p className="text-xs text-text-secondary">
                {item.reason}
              </p>
            </div>
          ))}
        </div>
      </div>

      <div className="flex-1 flex flex-col">
        <div className="flex-1 overflow-y-auto p-6 space-y-4">
          {commandHistory.map((message) => (
            <div
              key={message.id}
              className={`flex ${message.type === 'user' ? 'justify-end' : 'justify-start'}`}
            >
              <div
                className={`max-w-[70%] rounded-lg px-4 py-2 ${
                  message.type === 'user' ? 'bg-primary text-white' : 'bg-surface text-text'
                }`}
              >
                <div className="text-xs opacity-70 mb-1">
                  {message.type === 'user' ? 'user' : 'system'}
                </div>
                <div className="text-sm whitespace-pre-wrap">{message.content}</div>
                <div className="text-xs opacity-70 mt-1">
                  {message.timestamp.toLocaleTimeString('zh-CN', {
                    hour: '2-digit',
                    minute: '2-digit',
                  })}
                </div>
              </div>
            </div>
          ))}
        </div>

        <div className="border-t p-4 border-border bg-surface">
          <form onSubmit={handleSubmit} className="flex gap-2">
            <input
              type="text"
              value={inputValue}
              onChange={(e) => setInputValue(e.target.value)}
              placeholder="输入指令..."
              className="flex-1 px-4 py-2 border rounded-lg focus:outline-none focus:ring-2 border-border bg-background text-text"
            />
            <Button type="submit" variant="primary">
              <Send className="w-4 h-4 mr-2" />
              发送
            </Button>
          </form>
        </div>
      </div>
    </div>
  );
}