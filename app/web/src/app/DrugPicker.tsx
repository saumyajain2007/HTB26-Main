import styles from "./DrugPicker.module.css";

export interface DrugOption {
  id: string;
  name: string;
  disabled?: boolean;
}

interface DrugPickerProps {
  /** Accessible name, e.g. "Change drug". */
  label: string;
  value: string;
  options: readonly DrugOption[];
  onChange: (id: string) => void;
}

/** A drug's name set as a heading that is also the control that changes it. */
export function DrugPicker({ label, value, options, onChange }: DrugPickerProps) {
  return (
    <select
      className={styles.picker}
      aria-label={label}
      value={value}
      onChange={(event) => {
        onChange(event.target.value);
      }}
    >
      {options.map((option) => (
        <option key={option.id} value={option.id} disabled={option.disabled}>
          {option.name}
        </option>
      ))}
    </select>
  );
}
