const DRAFT_ID_KEY = "intake_consult_draft_id";
const CLIENT_ID_KEY = "intake_consult_client_id";

export const consultStorage = {
  getDraftId: () => sessionStorage.getItem(DRAFT_ID_KEY),
  getClientId: () => sessionStorage.getItem(CLIENT_ID_KEY),
  set: (draft_id: string, client_id: string) => {
    sessionStorage.setItem(DRAFT_ID_KEY, draft_id);
    sessionStorage.setItem(CLIENT_ID_KEY, client_id);
  },
  clear: () => {
    sessionStorage.removeItem(DRAFT_ID_KEY);
    sessionStorage.removeItem(CLIENT_ID_KEY);
  },
};

