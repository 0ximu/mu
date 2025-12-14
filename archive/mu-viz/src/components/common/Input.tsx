import { forwardRef, type InputHTMLAttributes } from 'react';

interface InputProps extends InputHTMLAttributes<HTMLInputElement> {
  label?: string;
}

export const Input = forwardRef<HTMLInputElement, InputProps>(
  ({ label, className = '', ...props }, ref) => {
    return (
      <div className="flex flex-col gap-1">
        {label && (
          <label className="font-bauhaus-label text-bauhaus-black">
            {label}
          </label>
        )}
        <input
          ref={ref}
          className={`
            w-full
            px-3 py-2
            bg-bauhaus-white
            border-2 border-bauhaus-black
            text-bauhaus-black
            font-medium
            placeholder:text-bauhaus-black/40
            focus:outline-none focus:ring-2 focus:ring-bauhaus-yellow focus:ring-offset-2
            ${className}
          `}
          {...props}
        />
      </div>
    );
  }
);

Input.displayName = 'Input';
