// Last line of defence: a crash while drawing a screen shows a way back instead of a blank app.
// It sits outside the language provider, so the message is in all three languages at once.

import React from 'react';
import { Text, TouchableOpacity, View } from 'react-native';

import { reportError } from './monitoring';

const MESSAGES = [
  'Something went wrong. Tap to try again.',
  'कुछ गड़बड़ हो गई। फिर से कोशिश करने के लिए टैप करें।',
  'ஏதோ தவறு நடந்தது. மீண்டும் முயல தட்டவும்.',
];

export default class ErrorBoundary extends React.Component {
  constructor(props) {
    super(props);
    this.state = { failed: false };
  }

  static getDerivedStateFromError() {
    return { failed: true };
  }

  componentDidCatch(error, info) {
    reportError(error, { componentStack: info?.componentStack });
  }

  render() {
    if (!this.state.failed) return this.props.children;
    return (
      <View style={{ flex: 1, alignItems: 'center', justifyContent: 'center', padding: 32, backgroundColor: '#FFFFFF' }}>
        <TouchableOpacity onPress={() => this.setState({ failed: false })} accessibilityRole="button"
          style={{ padding: 20, borderRadius: 12, borderWidth: 1, borderColor: '#E4E7EC' }}>
          {MESSAGES.map((message) => (
            <Text key={message} style={{ fontSize: 16, color: '#101828', textAlign: 'center', marginVertical: 6 }}>{message}</Text>
          ))}
        </TouchableOpacity>
      </View>
    );
  }
}
