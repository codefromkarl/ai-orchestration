import { cn } from '../utils/theme-utils';

interface ButtonProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: 'primary' | 'ghost' | 'danger';
  size?: 'default' | 'small';
}

export function Button({ 
  className, 
  variant = 'primary', 
  size = 'default',
  children,
  ...props 
}: ButtonProps) {
  return (
    <button
      className={cn(
        'inline-flex items-center justify-center rounded-md font-medium transition-all',
        'hover:-translate-y-0.5 active:translate-y-0',
        'focus:outline-none focus:ring-2 focus:ring-offset-2',
        {
          'bg-gradient-to-r from-[var(--color-primary)] to-[var(--color-primary-hover)] text-white shadow-sm': variant === 'primary',
          'bg-transparent hover:bg-[var(--color-surface-hover)]': variant === 'ghost',
          'bg-gradient-to-r from-red-600 to-red-700 text-white': variant === 'danger',
        },
        {
          'h-10 px-4 text-sm': size === 'default',
          'h-8 px-3 text-xs': size === 'small',
        },
        className
      )}
      {...props}
    >
      {children}
    </button>
  );
}