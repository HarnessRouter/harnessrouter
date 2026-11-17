import { createRoot } from 'react-dom/client';
import './styles.css';
import { AppBackendClient } from './AppBackendClient';

createRoot(document.getElementById('root')!).render(<AppBackendClient />);
