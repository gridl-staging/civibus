export type FilterOption = Readonly<{
  code: string;
  label: string;
}>;

export const FEC_CANDIDATE_OFFICE_OPTIONS: readonly FilterOption[] = [
  { code: "H", label: "U.S. House" },
  { code: "S", label: "U.S. Senate" },
  { code: "P", label: "President" }
];

export const COMMITTEE_TYPE_OPTIONS: readonly FilterOption[] = [
  { code: "C", label: "Communication Cost" },
  { code: "D", label: "Delegate Committee" },
  { code: "E", label: "Electioneering Communication" },
  { code: "H", label: "House Campaign" },
  { code: "I", label: "Independent Expenditor" },
  { code: "N", label: "PAC (Nonqualified)" },
  { code: "O", label: "Super PAC" },
  { code: "P", label: "Presidential Campaign" },
  { code: "Q", label: "PAC (Qualified)" },
  { code: "S", label: "Senate Campaign" },
  { code: "U", label: "Single-Candidate IE" },
  { code: "V", label: "PAC (Noncontribution, Nonqualified)" },
  { code: "W", label: "PAC (Noncontribution, Qualified)" },
  { code: "X", label: "Party (Nonqualified)" },
  { code: "Y", label: "Party (Qualified)" },
  { code: "Z", label: "National Party Nonfederal" }
];

export const US_STATE_OPTIONS: readonly FilterOption[] = [
  { code: "AL", label: "Alabama" },
  { code: "AK", label: "Alaska" },
  { code: "AZ", label: "Arizona" },
  { code: "AR", label: "Arkansas" },
  { code: "CA", label: "California" },
  { code: "CO", label: "Colorado" },
  { code: "CT", label: "Connecticut" },
  { code: "DE", label: "Delaware" },
  { code: "DC", label: "District of Columbia" },
  { code: "FL", label: "Florida" },
  { code: "GA", label: "Georgia" },
  { code: "HI", label: "Hawaii" },
  { code: "ID", label: "Idaho" },
  { code: "IL", label: "Illinois" },
  { code: "IN", label: "Indiana" },
  { code: "IA", label: "Iowa" },
  { code: "KS", label: "Kansas" },
  { code: "KY", label: "Kentucky" },
  { code: "LA", label: "Louisiana" },
  { code: "ME", label: "Maine" },
  { code: "MD", label: "Maryland" },
  { code: "MA", label: "Massachusetts" },
  { code: "MI", label: "Michigan" },
  { code: "MN", label: "Minnesota" },
  { code: "MS", label: "Mississippi" },
  { code: "MO", label: "Missouri" },
  { code: "MT", label: "Montana" },
  { code: "NE", label: "Nebraska" },
  { code: "NV", label: "Nevada" },
  { code: "NH", label: "New Hampshire" },
  { code: "NJ", label: "New Jersey" },
  { code: "NM", label: "New Mexico" },
  { code: "NY", label: "New York" },
  { code: "NC", label: "North Carolina" },
  { code: "ND", label: "North Dakota" },
  { code: "OH", label: "Ohio" },
  { code: "OK", label: "Oklahoma" },
  { code: "OR", label: "Oregon" },
  { code: "PA", label: "Pennsylvania" },
  { code: "RI", label: "Rhode Island" },
  { code: "SC", label: "South Carolina" },
  { code: "SD", label: "South Dakota" },
  { code: "TN", label: "Tennessee" },
  { code: "TX", label: "Texas" },
  { code: "UT", label: "Utah" },
  { code: "VT", label: "Vermont" },
  { code: "VA", label: "Virginia" },
  { code: "WA", label: "Washington" },
  { code: "WV", label: "West Virginia" },
  { code: "WI", label: "Wisconsin" },
  { code: "WY", label: "Wyoming" }
];
