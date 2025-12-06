import { forwardRef, type ButtonHTMLAttributes, type ReactNode } from 'react';

type ButtonVariant = 'red' | 'blue' | 'yellow' | 'outline' | 'ghost';
type ButtonShape = 'square' | 'pill';

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant;
  shape?: ButtonShape;
  children: ReactNode;
}

const variantStyles: Record<ButtonVariant, string> = {
  red: 'bg-bauhaus-red text-white hover:bg-bauhaus-red/90',
  blue: 'bg-bauhaus-blue text-white hover:bg-bauhaus-blue/90',
  yellow: 'bg-bauhaus-yellow text-bauhaus-black hover:bg-bauhaus-yellow/90',
  outline: 'bg-bauhaus-white text-bauhaus-black hover:bg-bauhaus-muted',
  ghost: 'bg-transparent text-bauhaus-black hover:bg-bauhaus-muted border-none shadow-none',
};

const shapeStyles: Record<ButtonShape, string> = {
  square: 'rounded-none',
  pill: 'rounded-full',
};

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(
  ({ variant = 'blue', shape = 'square', className = '', children, disabled, ...props }, ref) => {
    const baseStyles = `
      inline-flex items-center justify-center gap-2
      px-4 py-2
      border-2 border-bauhaus-black
      shadow-bauhaus-md
      font-bold uppercase tracking-wider text-sm
      transition-all duration-200 ease-out
      active:translate-x-[2px] active:translate-y-[2px] active:shadow-none
      disabled:opacity-50 disabled:cursor-not-allowed disabled:active:translate-x-0 disabled:active:translate-y-0 disabled:active:shadow-bauhaus-md
    `;

    const isGhost = variant === 'ghost';

    return (
      <button
        ref={ref}
        className={`
          ${baseStyles}
          ${variantStyles[variant]}
          ${shapeStyles[shape]}
          ${isGhost ? '' : 'border-bauhaus'}
          ${className}
        `}
        disabled={disabled}
        {...props}
      >
        {children}
      </button>
    );
  }
);

Button.displayName = 'Button';
