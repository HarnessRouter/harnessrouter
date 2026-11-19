import { createRoot } from 'react-dom/client';
import './tokens.css';
import './styles.css';
import { AppBackendClient } from './AppBackendClient';

createRoot(document.getElementById('root')!).render(<AppBackendClient />);
