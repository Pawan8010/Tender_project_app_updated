import React from "react";

export default class ErrorBoundary extends React.Component {
  constructor(props) {
    super(props);
    this.state = { hasError: false };
  }

  static getDerivedStateFromError() {
    return { hasError: true };
  }

  componentDidCatch(error) {
    console.error("UI error boundary caught:", error);
  }

  render() {
    if (this.state.hasError) {
      return (
        <main className="errorBoundary">
          <h1>Something went wrong</h1>
          <p>The dashboard hit a display error. Your data is still safe.</p>
          <button className="primarySmall" type="button" onClick={() => window.location.reload()}>
            Reload Page
          </button>
        </main>
      );
    }
    return this.props.children;
  }
}
