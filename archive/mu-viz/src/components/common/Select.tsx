import { forwardRef, type SelectHTMLAttributes } from 'react';

interface SelectProps extends SelectHTMLAttributes<HTMLSelectElement> {
  label?: string;
  options: Array<{ value: string; label: string }>;
}

export const Select = forwardRef<HTMLSelectElement, SelectProps>(
  ({ label, options, className = '', ...props }, ref) => {
    return (
      <div className="flex flex-col gap-1">
        {label && (
          <label className="font-bauhaus-label text-bauhaus-black">
            {label}
          </label>
        )}
        <select
          ref={ref}
          className={`
            w-full
            px-3 py-2
            bg-bauhaus-white
            border-2 border-bauhaus-black
            text-bauhaus-black
            font-medium
            cursor-pointer
            focus:outline-none focus:ring-2 focus:ring-bauhaus-yellow focus:ring-offset-2
            ${className}
          `}
          {...props}
        >
          {options.map((opt) => (
            <option key={opt.value} value={opt.value}>
              {opt.label}
            </option>
          ))}
        </select>
      </div>
    );
  }
);

Select.displayName = 'Select';
