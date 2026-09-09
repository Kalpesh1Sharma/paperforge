import type { SVGProps } from "react";

type IconProps = SVGProps<SVGSVGElement>;

function IconBase({ children, ...props }: IconProps) {
  return (
    <svg
      aria-hidden="true"
      fill="none"
      viewBox="0 0 24 24"
      stroke="currentColor"
      strokeWidth="1.8"
      strokeLinecap="round"
      strokeLinejoin="round"
      {...props}
    >
      {children}
    </svg>
  );
}

export const ArrowRightIcon = (props: IconProps) => (
  <IconBase {...props}><path d="M5 12h14M13 6l6 6-6 6" /></IconBase>
);
export const CheckIcon = (props: IconProps) => (
  <IconBase {...props}><path d="m5 12 4 4L19 6" /></IconBase>
);
export const ChevronDownIcon = (props: IconProps) => (
  <IconBase {...props}><path d="m7 10 5 5 5-5" /></IconBase>
);
export const ClockIcon = (props: IconProps) => (
  <IconBase {...props}><circle cx="12" cy="12" r="9" /><path d="M12 7v5l3 2" /></IconBase>
);
export const FileIcon = (props: IconProps) => (
  <IconBase {...props}><path d="M7 3h7l4 4v14H7z" /><path d="M14 3v5h5M10 13h5M10 17h5" /></IconBase>
);
export const DownloadIcon = (props: IconProps) => (
  <IconBase {...props}><path d="M12 3v12M7 10l5 5 5-5M5 21h14" /></IconBase>
);
export const ExternalIcon = (props: IconProps) => (
  <IconBase {...props}><path d="M14 4h6v6M20 4l-9 9" /><path d="M18 13v6H5V6h6" /></IconBase>
);
export const RefreshIcon = (props: IconProps) => (
  <IconBase {...props}><path d="M20 7v5h-5M4 17v-5h5" /><path d="M6.1 8A7 7 0 0 1 18 6l2 2M17.9 16A7 7 0 0 1 6 18l-2-2" /></IconBase>
);
export const FolderIcon = (props: IconProps) => (
  <IconBase {...props}><path d="M3 7h7l2 2h9v10H3z" /></IconBase>
);
export const GridIcon = (props: IconProps) => (
  <IconBase {...props}><rect x="4" y="4" width="6" height="6" rx="1" /><rect x="14" y="4" width="6" height="6" rx="1" /><rect x="4" y="14" width="6" height="6" rx="1" /><rect x="14" y="14" width="6" height="6" rx="1" /></IconBase>
);
export const MenuIcon = (props: IconProps) => (
  <IconBase {...props}><path d="M4 7h16M4 12h16M4 17h16" /></IconBase>
);
export const PlusIcon = (props: IconProps) => (
  <IconBase {...props}><path d="M12 5v14M5 12h14" /></IconBase>
);
export const PencilIcon = (props: IconProps) => (
  <IconBase {...props}><path d="m4 20 4.2-1 10.6-10.6a2.1 2.1 0 0 0-3-3L5.2 16zM14.5 6.5l3 3" /></IconBase>
);
export const SearchIcon = (props: IconProps) => (
  <IconBase {...props}><circle cx="11" cy="11" r="7" /><path d="m16 16 4 4" /></IconBase>
);
export const SparkIcon = (props: IconProps) => (
  <IconBase {...props}><path d="m12 3 1.5 4.5L18 9l-4.5 1.5L12 15l-1.5-4.5L6 9l4.5-1.5zM18.5 15l.7 2.3 2.3.7-2.3.7-.7 2.3-.7-2.3-2.3-.7 2.3-.7z" /></IconBase>
);
export const TemplateIcon = (props: IconProps) => (
  <IconBase {...props}><rect x="4" y="3" width="16" height="18" rx="2" /><path d="M8 7h8M8 11h3M8 15h8M8 18h6" /></IconBase>
);
export const TrashIcon = (props: IconProps) => (
  <IconBase {...props}><path d="M4 7h16M9 7V4h6v3M7 7l1 13h8l1-13M10 11v5M14 11v5" /></IconBase>
);
