import './globals.css';

export const metadata = {
  title: 'Naukri AI Job Copilot | Abdul Razzaque Shaikh',
  description: 'Automated 100% Anti-Ban Job Application Agent with Next.js, Python, Playwright, and MySQL',
};

export default function RootLayout({ children }) {
  return (
    <html lang="en" className="dark">
      <body className="bg-[#070b12] text-slate-100 antialiased selection:bg-teal-500 selection:text-white">
        {children}
      </body>
    </html>
  );
}
